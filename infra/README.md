# AWS hosting and automatic production deployments

## What is ready

The `Test and deploy` GitHub Actions workflow tests pull requests and every push to `main`. Only passing `main` builds can assume the AWS deployment role. It builds and smoke-tests one Docker image, transfers that same image to the deployment job, pushes an immutable Git-SHA tag to ECR, then uses a restricted Systems Manager document to deploy it. No SSH port, SSH key, or long-lived AWS access key is required.

The CloudFormation stack creates one Amazon Linux 2023 `t3.small` EC2 instance, encrypted root and database disks, a static IP, a public subnet, HTTP/HTTPS security rules, ECR, a private encrypted S3 backup bucket, Secrets Manager, and narrowly scoped instance/deployment IAM roles. GitHub's OIDC trust is limited to `repo:kjdrake/saturday-club:ref:refs/heads/main`. Public pull requests cannot get production credentials.

AWS resources are **not created by committing this code**. The one-time bootstrap below must run in your AWS account. Until repository variables are configured, CI runs normally and the deploy job is skipped. Running the bootstrap creates billable resources; EC2, EBS, public IPv4, Secrets Manager, storage, and transfer charges apply. There is no NAT gateway or load balancer.

## One-time setup (AWS CloudShell)

You need an AWS identity permitted to create CloudFormation stacks and the IAM, VPC, EC2, EBS, ECR, S3, Secrets Manager, and SSM resources in `stack.yaml`. Choose your production AWS account first. This setup defaults to your selected region **us-east-1** and domain **4thandsoul.com**.

1. Open [AWS CloudShell](https://console.aws.amazon.com/cloudshell/home). Run:

   ```sh
   git clone https://github.com/kjdrake/saturday-club.git
   cd saturday-club
   bash infra/bootstrap.sh
   ```

   If already cloned, run `git pull --ff-only` first. The script asks for a region (default `us-east-1`), domain, and commissioner email. It shows your AWS identity and asks before creating resources. It reuses an existing GitHub OIDC provider if one is installed.

2. In your DNS provider, set an **A record** for the chosen domain to the printed `PUBLIC_IP`. Remove stale AAAA records; this stack only provisions IPv4. Wait for public DNS to resolve. The stack does not buy a domain or modify DNS.

3. Open [GitHub repository Actions variables](https://github.com/kjdrake/saturday-club/settings/variables/actions). Add the six non-secret variables printed by the script:

   | Name | CloudFormation output |
   | --- | --- |
   | `AWS_REGION` | `AwsRegion` |
   | `AWS_ROLE_ARN` | `DeploymentRoleArn` |
   | `ECR_REPOSITORY` | `EcrRepository` |
   | `EC2_INSTANCE_ID` | `InstanceId` |
   | `DEPLOY_DOCUMENT` | `DeployDocumentName` |
   | `APP_URL` | `AppUrl` |

   These are resource identifiers, not credentials. **Do not add AWS access keys to GitHub.**

4. Wait until the instance appears Online in **AWS Systems Manager → Fleet Manager**. Host bootstrap installs Docker/Compose, attaches the data disk, and configures scheduled backups. Stack completion alone does not prove host bootstrap succeeded. Inspect `/var/log/saturday-club-bootstrap.log` through a Systems Manager session if necessary.

5. Open [GitHub Actions](https://github.com/kjdrake/saturday-club/actions), select **Test and deploy → Run workflow → main**. Tests must pass before deployment starts. The first release also waits for valid HTTPS; DNS must point at this instance so Caddy can obtain a certificate.

6. Open the `AppUrl` output. Retrieve the generated initial admin password privately from **AWS Secrets Manager → RuntimeSecretArn → Retrieve secret value**. Use the commissioner email supplied during setup. Never paste the password into a GitHub issue, workflow log, or this chat. Add an optional `ODDS_API_KEY` to that same JSON secret; redeploy to apply it.

7. In [GitHub rulesets](https://github.com/kjdrake/saturday-club/settings/rules), create an active branch ruleset for `main`: require pull requests and require the **Tests and container smoke test** status check. Block force pushes and branch deletion. You can permit your own administrator bypass for emergencies. This setting may require account-owner action because the connector does not have repository Administration permission. Do not require an approving reviewer if you are the sole maintainer and have no reviewer available.

## Normal development

Create a branch, make changes, push, and open a PR. CI tests the backend, UI logic, infrastructure template, backup/SSM helper behavior, and the real Docker image. The container smoke test registers a member, verifies role enforcement, saves a pick, creates a backup, replaces the container, and verifies the saved pick remains.

Merge a passing PR into `main`. CI runs again on the merged commit, publishes the tested image, and deploys it. Deployments are serialized and additionally guarded by a host lock. The deploy role cannot execute arbitrary SSM shell commands; it can invoke only this stack's deploy document on its instance with a 40-character SHA image tag.

The host copies release-specific Compose/Caddy configuration from the tested image, retrieves runtime secrets, makes a SQLite-consistent backup before replacing an existing release, starts the new release, and checks both the app and local HTTPS endpoint using the real domain/certificate. A failed check restores the previous release's app, worker, and proxy configuration. A failed first deployment stops the new containers and preserves the data disk. Deployment failure remains a red workflow run even after successful rollback.

A missing/failed backup blocks deployment rather than replacing the current app without a backup. Schema migrations must remain backward-compatible with the previous image: automatic rollback **does not roll back database changes**. There are no destructive database migrations in this release.

## Operations and recovery

- Only ports 80 and 443 are open. Administrators use AWS Systems Manager; the GitHub deployment role cannot open sessions or access runtime secrets.
- Runtime files are root-readable under `/opt/saturday-club`. App data, TLS state, and backups are under `/srv/saturday-club` on the separate encrypted volume. The app runs as UID 10001.
- Daily SQLite backups run around 07:00 UTC (up to 15 minutes of randomized delay), as well as before deployments. SQLite's backup API includes committed WAL data. Backups upload over TLS with S3 encryption, expire after 35 days, and are removed from the host after a successful upload. Backup failures are visible in `journalctl -u saturday-club-backup.service`; monitoring/alerting is not provisioned by this stack.
- Check `docker ps`, `docker logs --tail=100 saturday-club-app`, and `docker logs --tail=100 saturday-club-scores` in an SSM session. Do not print `/opt/saturday-club/runtime.env` into shared logs.
- To redeploy a previous image, run the custom SSM document in **Systems Manager → Run Command**, using that previously deployed commit SHA. Versioned ECR images are retained to support rollback. Periodically prune old ECR tags/releases when they are no longer needed; retain the current and previous release.
- Retrieve a backup using an administrator identity with S3 read permission. To restore, first save the current database, stop both app and worker, replace `/srv/saturday-club/league/club.db`, remove obsolete `club.db-wal`/`club.db-shm`, set ownership to 10001:10001, and restart the current Compose release. Test restores before relying on the backup strategy. The instance IAM role can upload backups but intentionally cannot download or delete them.
- The generated admin password only creates the first account. Changing it in Secrets Manager does not reset an existing account's password.
- This is a single-server system with brief deployment downtime. It is not a multi-AZ service. ECR/secret/backup resources are retained on stack deletion; the data disk is snapshotted. Retained resources continue to incur charges.
- Infrastructure updates require reviewing a CloudFormation change set; do not blindly rerun bootstrap against an existing production stack. Host/bootstrap script changes do not rerun automatically on an existing instance. Runtime code and release Compose/Caddy configuration deploy from each tested image; changing base host setup requires a planned maintenance/instance replacement and checking the existing data-volume attachment.

## Local validation

```sh
python -m unittest discover -s tests -v
node tests/ui.cjs
python -m unittest discover -s infra/tests -v
for script in infra/*.sh; do bash -n "$script"; done
python -m pip install -r infra/requirements-checks.txt
cfn-lint infra/stack.yaml
docker build -t saturday-club:test .
python infra/smoke.py saturday-club:test
```
