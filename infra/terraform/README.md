# Terraform development environment

This directory owns the reproducible GCP development environment for POR-32. It
creates infrastructure only: the Cloud Run services use Google's public hello
container as an authenticated smoke image until the application deployment
issue replaces it. No production resources or application images are managed
here.

## What is created

- a custom VPC, serverless subnet, and private service connection;
- one private-IP PostgreSQL Cloud SQL instance and application database;
- one private, versioned raw-source Cloud Storage bucket;
- API, admin, and worker Cloud Run v2 services with direct VPC egress;
- one Cloud Tasks queue;
- empty Secret Manager containers (never secret versions or payloads);
- separate API, admin, and worker runtime service accounts;
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
7. Re-run `plan`; expect no changes.

## Cleanup and destroy policy

Development infrastructure is disposable, but cleanup is intentional:

- `deletion_protection` defaults to `true` for Cloud SQL and Cloud Run. For
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
