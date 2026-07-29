# Terraform development environment

This directory owns the reproducible GCP development environment. Terraform
bootstraps API, admin, and worker services with Google's public hello container;
the deployment pipeline then owns their image revisions. POR-34 adds the
health-only API delivery path and keyless GitHub identities. No production
resources are managed here.

## What is created

- a custom VPC, serverless subnet, and private service connection;
- one private-IP PostgreSQL Cloud SQL instance and application database;
- Cloud SQL IAM database authentication and a dedicated migration database user;
- one private Artifact Registry Docker repository with immutable tags;
- one private, versioned raw-source Cloud Storage bucket;
- API, admin, and worker Cloud Run v2 services with direct VPC egress; only the
  health-only API is publicly callable in M0;
- an optional, digest-pinned Cloud Run migration job with direct VPC egress;
- one Cloud Tasks queue;
- empty Secret Manager containers (never secret versions or payloads);
- separate API, admin, worker, and migration runtime service accounts;
- separate keyless GitHub image-publisher and development-deployer service
  accounts;
- narrowly scoped project IAM bindings for runtime logging, monitoring, and
  Cloud SQL, plus resource-scoped Storage, Secret Manager, and Cloud Tasks
  access; and
- required Google APIs.

Resources that support labels receive `application=rag-support-chatbot`,
`environment=dev`, and `managed_by=terraform`. Other resources use the same
`rag-dev` naming prefix and descriptions.

## Prerequisites

Follow the repository bootstrap in the root `README.md`, then authenticate
Application Default Credentials and select a billed development project:

```sh
gcloud auth application-default login
gcloud config set project YOUR_DEVELOPMENT_PROJECT_ID
```

The caller needs permission to enable APIs, create the resources above, and
manage the listed IAM bindings. Cloud SQL requires billing, Service Networking
API quota, and an available private-service address range.

Do not place credentials or secret values in `.tfvars`, environment variables,
Terraform outputs, or state. Runtime secret values are added later through an
approved secret-delivery workflow.

## 1. Bootstrap remote state

The state bucket is deliberately isolated in `bootstrap/` to avoid a
chicken-and-egg dependency. Choose a globally unique bucket name, copy the
example variables, and apply once:

```sh
cp infra/terraform/bootstrap/terraform.tfvars.example \
  infra/terraform/bootstrap/terraform.tfvars
terraform -chdir=infra/terraform/bootstrap init
terraform -chdir=infra/terraform/bootstrap plan -out=bootstrap.tfplan
terraform -chdir=infra/terraform/bootstrap apply bootstrap.tfplan
```

The bucket enforces uniform access, public-access prevention, versioning, and a
30-day minimum retention policy. Keep the small bootstrap state file in a
restricted operator location until the state bucket lifecycle is formally
transferred; never commit it.

## 2. Configure and plan development

Copy the examples and replace only non-secret values:

```sh
cp infra/terraform/environments/dev/backend.hcl.example \
  infra/terraform/environments/dev/backend.hcl
cp infra/terraform/environments/dev/dev.tfvars.example \
  infra/terraform/environments/dev/dev.tfvars
```

Initialize the GCS backend and create a reviewable plan:

```sh
terraform -chdir=infra/terraform init \
  -backend-config=environments/dev/backend.hcl
terraform -chdir=infra/terraform plan \
  -var-file=environments/dev/dev.tfvars \
  -out=dev.tfplan
terraform -chdir=infra/terraform show dev.tfplan
```

The configuration has no random or time-based resource names. After a
successful apply, a second plan should report `No changes`. Treat any repeated
diff as a release blocker and inspect the provider/version lock and changed
inputs before applying.

## 3. Apply and inspect

Applying creates billable resources, especially Cloud SQL:

```sh
terraform -chdir=infra/terraform apply dev.tfplan
terraform -chdir=infra/terraform output
```

The first POR-33 apply leaves `migration_image` unset. It creates the private
image repository, enables Cloud SQL IAM authentication, and creates the
passwordless migration identity. The Cloud Run job is created only after an
immutable migration image is available.

Manual verification:

1. Confirm the three standard labels on Cloud Run, Cloud SQL, Storage, and
   Secret Manager resources.
2. Confirm the raw-source bucket has public-access prevention and uniform bucket
   access enabled, with no public IAM members.
3. Confirm Cloud SQL has no public IPv4 address and is attached to the custom
   VPC through private service networking.
4. Confirm Cloud Run ingress is restricted and each service uses its dedicated
   service account.
5. Confirm API and worker service accounts are different, neither has Owner or
   Editor, their project roles match `locals.tf`, and Storage, Secret Manager,
   and Cloud Tasks access is bound directly to the respective resource.
6. Confirm Secret Manager contains metadata only and Terraform created no secret
   versions.
7. Confirm the migration service account has Cloud SQL Client and Cloud SQL
   Instance User, but no Secret Manager access.
8. Confirm the CI publisher can only write the managed Artifact Registry
   repository, while the deployer can read it, update Cloud Run, and act only as
   the API and migration runtime identities.
9. Re-run `plan`; expect no changes.

## 4. Build and configure the migration job

Authenticate Docker to the regional registry:

```sh
gcloud auth configure-docker europe-west1-docker.pkg.dev
terraform -chdir=infra/terraform output -raw artifact_registry_repository_url
```

Use the output as `REPOSITORY`, build from a clean POR-33 commit, and push a tag
containing that commit:

```sh
docker build \
  --platform linux/amd64 \
  --file apps/api/Dockerfile.migrations \
  --tag REPOSITORY/migrations:POR-33-COMMIT \
  .
docker push REPOSITORY/migrations:POR-33-COMMIT
gcloud artifacts docker images describe \
  REPOSITORY/migrations:POR-33-COMMIT \
  --format='value(image_summary.digest)'
```

Set the ignored development variable to the repository plus returned digest:

```hcl
migration_image = "REPOSITORY/migrations@sha256:RETURNED_DIGEST"
```

Review and apply the second phase:

```sh
terraform -chdir=infra/terraform plan \
  -var-file=environments/dev/dev.tfvars \
  -out=migration-job.tfplan
terraform -chdir=infra/terraform apply migration-job.tfplan
```

Terraform rejects tags or images outside its managed repository. The job uses a
dedicated IAM database user and receives no password or Secret Manager value.

## 5. Run and verify migrations

Execute the job twice:

```sh
gcloud run jobs execute rag-dev-migrate --region=europe-west1 --wait
gcloud run jobs execute rag-dev-migrate --region=europe-west1 --wait
```

Each successful execution logs only the Alembic revision, pgvector extension
version, and a harmless vector-cast probe. Both runs must report
`0001_enable_pgvector`; the second run must apply no revision. Inspect job logs
or Cloud SQL Studio and confirm:

```sql
SELECT version_num FROM rag_app.alembic_version;
SELECT extversion FROM pg_extension WHERE extname = 'vector';
SELECT '[1,2,3]'::vector;
```

Finally, confirm the Cloud SQL instance is `RUNNABLE`, the latest two job
executions succeeded, and another Terraform plan reports no changes.

## 6. Configure keyless GitHub delivery

Terraform creates a GitHub OIDC provider restricted to the repository's
immutable numeric repository and owner IDs. It creates two separate identities:

- `publisher` accepts only the exact `main` branch OIDC subject and can write
  images only to the managed Artifact Registry repository.
- `deployer` accepts only the `development` environment OIDC subject, can read
  that repository and update Cloud Run, and may act only as the API and
  migration runtime service accounts.

Apply the ordinary development plan, then obtain the non-secret values:

```sh
terraform -chdir=infra/terraform output -raw github_workload_identity_provider
terraform -chdir=infra/terraform output -json automation_service_account_emails
terraform -chdir=infra/terraform output -raw artifact_registry_repository_url
```

Create these GitHub Actions repository variables:

| Variable                         | Value                                         |
| -------------------------------- | --------------------------------------------- |
| `GCP_PROJECT_ID`                 | Terraform `project_id` output                 |
| `GCP_REGION`                     | Terraform `region` output                     |
| `GCP_ARTIFACT_REPOSITORY`        | Repository ID only, normally `rag-dev-images` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Full provider output                          |
| `GCP_PUBLISHER_SERVICE_ACCOUNT`  | `publisher` automation account email          |
| `GCP_DEPLOYER_SERVICE_ACCOUNT`   | `deployer` automation account email           |

Do not create a JSON service-account key or store cloud credentials in GitHub
secrets.

In GitHub repository settings, create the `development` environment and require
the repository owner as a reviewer. Keep "prevent self-review" disabled while
there is only one operator, otherwise no deployment can be approved. Restrict
deployment branches to `main`. Also require the `Quality / Repository checks`
status check before merging to `main`.

The main-branch publication workflow first runs `mise run check`, then builds
and pushes `api:FULL_COMMIT_SHA` and `migrations:FULL_COMMIT_SHA`. Artifact
Registry rejects tag reuse, and the workflow retains a manifest containing the
resolved `sha256` digests.

To deploy:

1. Open **Actions → Deploy development → Run workflow**.
2. Enter the full 40-character SHA from a successful main publication.
3. Review and approve the waiting `development` job.
4. Confirm the job runs the migration before updating the API.
5. Download the retained deployment artifact and compare its API digest and
   revision with Cloud Run.
6. Open the recorded `/healthz` URL and confirm `status=ok` and
   `source_revision` equals the approved SHA.

Terraform continues to own Cloud Run configuration and deletion protection.
The delivery workflows own only service/job image revisions, which Terraform
intentionally ignores so a post-deployment plan remains stable.

## Cleanup and destroy policy

Development infrastructure is disposable, but cleanup is intentional:

- `deletion_protection` defaults to `true` for Cloud SQL and Cloud Run services
  and jobs. For
  Cloud SQL, it enables both Terraform-side deletion protection and GCP's
  instance-level console/API protection.
- The disposable development Cloud SQL instance does not retain a final backup
  after an intentional deletion; routine backups and point-in-time recovery
  remain enabled while the instance exists.
- `allow_destructive_cleanup` defaults to `false`, so Terraform will not empty
  the raw-source bucket during destroy.
- API enablement remains in place after destroy to avoid disrupting resources
  outside this state.
- The remote-state bucket is managed separately and must be destroyed last.

To retire an environment, first retain any required documents, logs, and
database backups. Disable both safeguards with a normal apply so Terraform
persists the transition before attempting to delete the protected resources:

```sh
terraform -chdir=infra/terraform plan \
  -var-file=environments/dev/dev.tfvars \
  -var='deletion_protection=false' \
  -var='allow_destructive_cleanup=true' \
  -out=prepare-destroy.tfplan
terraform -chdir=infra/terraform apply prepare-destroy.tfplan

terraform -chdir=infra/terraform plan \
  -destroy \
  -var-file=environments/dev/dev.tfvars \
  -var='deletion_protection=false' \
  -var='allow_destructive_cleanup=true' \
  -out=destroy.tfplan
terraform -chdir=infra/terraform apply destroy.tfplan
```

The preparatory apply does not delete resources, but it removes their deletion
safeguards. If cleanup is canceled, immediately reapply the ordinary
development variables to restore protection.

After confirming the main state is empty, wait for the state bucket's 30-day
retention window, remove retained object versions, and destroy `bootstrap/`.
Never delete state or cloud resources manually as a shortcut; import or
reconcile drift with Terraform.

## Automated verification

The repository quality command initializes both roots without a backend,
validates them, runs mocked Terraform plans with policy assertions, and checks
the explicit output allowlist:

```sh
mise run test:terraform
mise run check
```

These tests require no GCP credentials and create no cloud resources. A real
development `plan` and `apply` remain manual, credentialed verification because
they affect a billed external project.
