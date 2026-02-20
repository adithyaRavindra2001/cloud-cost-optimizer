import json
import anthropic
from typing import Optional


def generate_recommendations(analysis_data: dict, api_key: str) -> dict:
    """Send cost analysis data to Claude and get structured recommendations."""
    client = anthropic.Anthropic(api_key=api_key)

    # Build a concise summary for the prompt
    summary = _build_cost_summary(analysis_data)

    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": f"""You are a senior AWS cloud cost optimization consultant. Analyze the following cloud cost data and provide actionable recommendations.

{summary}

Respond with ONLY valid JSON in this exact format (no markdown, no code fences):
{{
  "summary": "A 2-3 sentence executive summary of the cost situation",
  "total_estimated_monthly_savings": <number>,
  "recommendations": [
    {{
      "title": "Short actionable title",
      "category": "one of: compute, storage, database, networking, architecture, purchasing",
      "priority": "one of: critical, high, medium, low",
      "estimated_monthly_savings": <number or 0 if unknown>,
      "effort": "one of: quick-win, moderate, significant",
      "description": "2-3 sentence explanation of what to do and why",
      "affected_resources": ["resource-id-1", "resource-id-2"]
    }}
  ]
}}

Give 5-8 specific, actionable recommendations based on the actual data provided. Be specific about which resources to act on. Prioritize by savings impact.""",
            }
        ],
    )

    response_text = message.content[0].text.strip()

    # Parse the JSON response
    try:
        recommendations = json.loads(response_text)
    except json.JSONDecodeError:
        # Try to extract JSON from the response if it has extra text
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start >= 0 and end > start:
            recommendations = json.loads(response_text[start:end])
        else:
            recommendations = {
                "summary": "Unable to parse AI recommendations.",
                "total_estimated_monthly_savings": 0,
                "recommendations": [],
            }

    return recommendations


def _build_cost_summary(data: dict) -> str:
    """Build a concise text summary of the cost data for the prompt."""
    parts = []

    # Monthly cost
    mc = data.get("monthly_cost", {})
    parts.append(f"MONTHLY SPEND: ${mc.get('total_cost', 0):,.2f} ({mc.get('period', 'current month')})")

    # Top services
    services = data.get("top_services", [])
    if services:
        parts.append("\nTOP SERVICES BY COST:")
        for s in services[:10]:
            parts.append(f"  - {s['service']}: ${s['cost']:,.2f}")

    # Resource costs
    resources = data.get("resource_costs", [])
    if resources:
        parts.append(f"\nTOP RESOURCES BY COST ({len(resources)} total):")
        for r in resources[:15]:
            name = r.get("name") or r["resource_id"]
            parts.append(f"  - {name} ({r['resource_type']}): ${r['cost']:,.2f} — {r['service']}")

    # Idle instances
    savings = data.get("savings_opportunities", {})
    idle = savings.get("idle_ec2_instances", {})
    if idle.get("items"):
        parts.append(f"\nIDLE EC2 INSTANCES ({idle['count']} found, ${idle['potential_savings']:,.2f}/mo savings):")
        for item in idle["items"]:
            cpu_info = ""
            if item.get("avg_cpu") is not None:
                net = ((item.get("avg_network_in") or 0) + (item.get("avg_network_out") or 0)) / 1_000_000
                cpu_info = f" | CPU: {item['avg_cpu']}%, Network: {net:.2f} MB/hr"
            parts.append(f"  - {item['instance_id']} ({item['instance_type']}): ${item['estimated_monthly_cost']}/mo{cpu_info}")

    # Unattached volumes
    vols = savings.get("unattached_ebs_volumes", {})
    if vols.get("items"):
        parts.append(f"\nUNATTACHED EBS VOLUMES ({vols['count']} found, ${vols['potential_savings']:,.2f}/mo savings):")
        for item in vols["items"]:
            parts.append(f"  - {item['volume_id']} ({item.get('volume_type', 'unknown')}, {item['size_gb']}GB): ${item['estimated_monthly_cost']}/mo")

    # Old snapshots
    snaps = savings.get("old_snapshots", {})
    if snaps.get("items"):
        parts.append(f"\nOLD SNAPSHOTS ({snaps['count']} found, ${snaps['potential_savings']:,.2f}/mo savings):")
        for item in snaps["items"]:
            parts.append(f"  - {item['snapshot_id']} ({item.get('age_days', '?')} days old, {item.get('size_gb', '?')}GB): ${item['estimated_monthly_cost']}/mo")

    # Anomalies
    anomalies = data.get("anomalies", [])
    if anomalies:
        parts.append(f"\nCOST ANOMALIES ({len(anomalies)} detected):")
        for a in anomalies:
            parts.append(f"  - [{a['severity'].upper()}] {a['service']} on {a['date']}: expected ${a['expected_cost']:.2f}, actual ${a['actual_cost']:.2f} (+${a['impact']:.2f}, +{a['impact_percentage']:.0f}%)")

    # Deep dive findings
    deep_dive = data.get("deep_dive", {})
    if deep_dive:
        parts.append("\nDEEP DIVE FINDINGS (per-service resource inspection):")
        for service_name, details in deep_dive.items():
            resources = details.get("resources", [])
            findings = details.get("findings", [])
            parts.append(f"\n  [{service_name}] — {len(resources)} resources inspected")
            for r in resources[:10]:
                # Build a compact one-line summary of each resource
                summary_parts = []
                for k, v in r.items():
                    summary_parts.append(f"{k}={v}")
                parts.append(f"    • {', '.join(summary_parts)}")
            if findings:
                parts.append(f"  Findings ({len(findings)}):")
                for f in findings:
                    parts.append(f"    ⚠ {f}")

    # Daily cost trend summary
    daily = data.get("daily_costs", [])
    if daily:
        costs = [d["cost"] for d in daily]
        avg = sum(costs) / len(costs)
        parts.append(f"\n30-DAY TREND: avg ${avg:,.2f}/day, min ${min(costs):,.2f}, max ${max(costs):,.2f}")

    return "\n".join(parts)
