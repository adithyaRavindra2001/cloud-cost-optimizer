"""Chat agent with Claude tool_use for AWS cost investigation."""

import os
import json
import anthropic
from services.aws_tools import (
    get_cost_by_service,
    get_daily_costs,
    compare_cost_periods,
    get_cost_by_usage_type,
    describe_ec2_instances,
    describe_ecs_services,
    describe_rds_instances,
    get_cloudwatch_metrics,
    DEMO_TOOLS,
)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

TOOL_DEFINITIONS = [
    {
        "name": "get_cost_by_service",
        "description": "Get AWS costs broken down by service for a date range. Returns top services sorted by cost.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                "limit": {"type": "integer", "description": "Max services to return (default 10)"},
            },
            "required": ["start_date", "end_date"],
        },
    },
    {
        "name": "get_daily_costs",
        "description": "Get daily cost breakdown for a date range. Optionally filter by a specific AWS service name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                "service_filter": {"type": "string", "description": "Optional: exact AWS service name to filter by"},
            },
            "required": ["start_date", "end_date"],
        },
    },
    {
        "name": "compare_cost_periods",
        "description": "Compare total costs between two time periods and compute the delta and percentage change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "p1_start": {"type": "string", "description": "Period 1 start date (YYYY-MM-DD)"},
                "p1_end": {"type": "string", "description": "Period 1 end date (YYYY-MM-DD)"},
                "p2_start": {"type": "string", "description": "Period 2 start date (YYYY-MM-DD)"},
                "p2_end": {"type": "string", "description": "Period 2 end date (YYYY-MM-DD)"},
            },
            "required": ["p1_start", "p1_end", "p2_start", "p2_end"],
        },
    },
    {
        "name": "get_cost_by_usage_type",
        "description": "Get costs grouped by usage type (e.g., BoxUsage:m5.xlarge, DataTransfer-Out-Bytes). Useful for understanding what exactly drives cost within a service.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
                "end_date": {"type": "string", "description": "End date (YYYY-MM-DD)"},
                "service_filter": {"type": "string", "description": "Optional: exact AWS service name to filter by"},
            },
            "required": ["start_date", "end_date"],
        },
    },
    {
        "name": "describe_ec2_instances",
        "description": "List EC2 instances with their type, state, and name. Optionally filter by state (running, stopped, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "state_filter": {"type": "string", "description": "Optional: instance state filter (running, stopped, etc.)"},
            },
            "required": [],
        },
    },
    {
        "name": "describe_ecs_services",
        "description": "List ECS services across clusters with their task counts, launch type, CPU/memory config.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cluster": {"type": "string", "description": "Optional: specific ECS cluster name or ARN"},
            },
            "required": [],
        },
    },
    {
        "name": "describe_rds_instances",
        "description": "List all RDS database instances with their class, engine, storage, and Multi-AZ status.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_cloudwatch_metrics",
        "description": "Query CloudWatch metrics for any AWS resource. Useful for checking CPU utilization, network traffic, disk I/O, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string", "description": "CloudWatch namespace (e.g., AWS/EC2, AWS/RDS, AWS/ECS)"},
                "metric_name": {"type": "string", "description": "Metric name (e.g., CPUUtilization, NetworkIn)"},
                "dimension_name": {"type": "string", "description": "Dimension name (e.g., InstanceId, DBInstanceIdentifier)"},
                "dimension_value": {"type": "string", "description": "Dimension value (e.g., i-0abc123)"},
                "days": {"type": "integer", "description": "Number of days to look back (default 7)"},
                "stat": {"type": "string", "description": "Statistic: Average, Maximum, Minimum, Sum (default Average)"},
            },
            "required": ["namespace", "metric_name", "dimension_name", "dimension_value"],
        },
    },
]

# Map tool names to real implementations
TOOL_FUNCTIONS = {
    "get_cost_by_service": get_cost_by_service,
    "get_daily_costs": get_daily_costs,
    "compare_cost_periods": compare_cost_periods,
    "get_cost_by_usage_type": get_cost_by_usage_type,
    "describe_ec2_instances": describe_ec2_instances,
    "describe_ecs_services": describe_ecs_services,
    "describe_rds_instances": describe_rds_instances,
    "get_cloudwatch_metrics": get_cloudwatch_metrics,
}

SYSTEM_PROMPT = """You are an expert AWS FinOps analyst embedded in a cost optimization dashboard. The user is looking at their AWS cost analysis and wants to ask follow-up questions.

Current analysis context:
{context}

Today's date: {today}

Guidelines:
- Use the provided tools to investigate the user's questions by making real AWS API calls.
- Be specific with numbers and percentages. Always cite the data you retrieved.
- When comparing periods, use compare_cost_periods. When drilling into a service, use get_cost_by_usage_type.
- Keep answers concise but actionable. Suggest specific next steps.
- If you need multiple pieces of data, call multiple tools.
- Format currency as $X,XXX.XX. Use markdown for readability."""


def _execute_tool(tool_name, tool_input, creds, region, demo):
    """Execute a tool, either demo or real."""
    if demo:
        fn = DEMO_TOOLS.get(tool_name)
        if fn:
            return fn(**tool_input)
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    fn = TOOL_FUNCTIONS.get(tool_name)
    if not fn:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    # Inject creds and region for real calls
    return fn(creds, region, **tool_input)


def run_chat(messages, aws_creds=None, region="us-east-1", analysis_context="", demo=False):
    """
    Agentic loop: call Claude with tools, execute any tool_use blocks,
    feed results back, repeat until end_turn or max iterations.

    Returns: (response_text, tools_used)
    """
    from datetime import date

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    system = SYSTEM_PROMPT.format(
        context=analysis_context[:3000] if analysis_context else "No analysis loaded yet.",
        today=str(date.today()),
    )

    tools_used = []
    max_iterations = 5

    # Convert messages to Anthropic format
    api_messages = []
    for m in messages:
        api_messages.append({"role": m["role"], "content": m["content"]})

    for _ in range(max_iterations):
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=2048,
            system=system,
            tools=TOOL_DEFINITIONS,
            messages=api_messages,
        )

        if response.stop_reason == "end_turn":
            # Extract text from content blocks
            text_parts = [b.text for b in response.content if b.type == "text"]
            return "\n".join(text_parts), tools_used

        if response.stop_reason == "tool_use":
            # Append assistant response (includes tool_use blocks)
            api_messages.append({"role": "assistant", "content": response.content})

            # Execute each tool call
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tools_used.append(block.name)
                    try:
                        result = _execute_tool(
                            block.name, block.input,
                            aws_creds, region, demo,
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                    except Exception as e:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps({"error": str(e)}),
                            "is_error": True,
                        })

            api_messages.append({"role": "user", "content": tool_results})
        else:
            # Unexpected stop reason, return whatever text we have
            text_parts = [b.text for b in response.content if b.type == "text"]
            return "\n".join(text_parts) or "I wasn't able to complete the investigation.", tools_used

    # Max iterations reached
    text_parts = [b.text for b in response.content if b.type == "text"]
    return "\n".join(text_parts) or "I've reached the maximum number of investigation steps. Here's what I found so far.", tools_used
