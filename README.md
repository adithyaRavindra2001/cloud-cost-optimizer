# Cloud Cost Optimizer

A full-stack application to analyze AWS cloud spending, surface savings opportunities, and chat with an AI agent about your costs.

## Prerequisites

- Python 3.10+
- Node.js 20 (see `frontend/.nvmrc`)
- PostgreSQL

---

## 1. Clone & set up the backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in every value:

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string, e.g. `postgresql://localhost/cloud_cost_optimizer` |
| `JWT_SECRET` | Long random string used to sign auth tokens |
| `ENCRYPTION_KEY` | Fernet key used to encrypt stored cloud credentials at rest |
| `ANTHROPIC_API_KEY` | *(Optional)* Enables AI recommendations and the chat agent |

**Generate a Fernet encryption key:**

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Create the database

```bash
createdb cloud_cost_optimizer   # or use psql / your Postgres client
```

The app auto-creates all tables on first startup.

### Start the backend

```bash
uvicorn main:app --reload --port 8000
```

API is now available at `http://localhost:8000`.

---

## 2. Set up the frontend

```bash
cd frontend
npm install
```

The frontend expects the backend at `http://localhost:8000` by default. If you changed the port, update `frontend/.env.local`:

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### Start the frontend

```bash
npm run dev
```

App is now available at `http://localhost:3000`.

---

## 3. Add your AWS credentials

Once logged in, go to **Settings → Add Credentials** and provide:

| Field | Description |
|---|---|
| AWS Access Key ID | From IAM → your user → Security credentials |
| AWS Secret Access Key | From the same place |
| Region | e.g. `us-east-1` |

### Required IAM permissions

The access keys need **read-only** access. Attach this inline policy (or use the AWS-managed `ReadOnlyAccess` policy):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ce:GetCostAndUsage",
        "ce:GetAnomalyMonitors",
        "ce:GetAnomalies",
        "ec2:DescribeInstances",
        "ec2:DescribeVolumes",
        "ec2:DescribeSnapshots",
        "rds:DescribeDBInstances",
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:GetMetricData",
        "ecs:ListClusters",
        "ecs:ListServices",
        "ecs:DescribeServices",
        "s3:ListAllMyBuckets",
        "s3:GetBucketLifecycleConfiguration",
        "lambda:ListFunctions"
      ],
      "Resource": "*"
    }
  ]
}
```

The app never modifies or deletes any resources.

---

## 4. Try the demo

No AWS account? Hit **Try Demo** on the login page to explore the app with realistic sample data — no credentials needed.

---

## Project structure

```
cloud-cost-optimizer/
├── backend/
│   ├── main.py               # FastAPI app & all API routes
│   ├── database.py           # SQLAlchemy engine & session
│   ├── models/               # Pydantic & SQLAlchemy models
│   ├── providers/            # Cloud provider adapters (AWS, GCP, Azure)
│   ├── services/             # Auth, encryption, AI chat agent, recommendations
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    ├── app/                  # Next.js app router pages
    ├── package.json
    └── .env.local
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, Tailwind CSS 4, Recharts |
| Backend | FastAPI, SQLAlchemy, Uvicorn |
| Database | PostgreSQL |
| AI | Anthropic Claude (claude-sonnet-4-6) |
| Cloud SDK | boto3 (AWS) |
