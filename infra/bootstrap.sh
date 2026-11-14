#!/usr/bin/env bash
# Run in AWS CloudShell (or a terminal already authenticated to your AWS account).
set -euo pipefail
cd "$(dirname "$0")/.."
command -v aws >/dev/null || { echo 'Run this in AWS CloudShell or install AWS CLI v2.' >&2; exit 1; }
aws sts get-caller-identity --query '{Account:Account,Arn:Arn}' --output table
read -r -p 'AWS region [us-east-1]: ' region
region=${region:-us-east-1}
read -r -p 'Production domain [4thandsoul.com]: ' domain
domain=${domain:-4thandsoul.com}
read -r -p 'Initial commissioner email: ' email
read -r -p 'Stack name [saturday-club-prod]: ' stack
stack=${stack:-saturday-club-prod}
[[ "$domain" =~ ^[a-z0-9][a-z0-9.-]+\.[a-z]{2,}$ ]] || { echo 'Enter a valid lowercase domain.' >&2; exit 1; }
[[ "$email" =~ ^[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || { echo 'Enter a valid email.' >&2; exit 1; }
sha=$(git rev-parse HEAD)
repository=$(git remote get-url origin | sed -E 's#https://github.com/##;s#\.git$##')
[[ "$repository" == 'kjdrake/saturday-club' ]] || { echo 'Run from a clone of kjdrake/saturday-club.' >&2; exit 1; }
provider=$(aws iam list-open-id-connect-providers --query "OpenIDConnectProviderList[?ends_with(Arn, 'oidc-provider/token.actions.githubusercontent.com')].Arn | [0]" --output text)
[[ "$provider" == None ]] && provider=''
cat <<'NOTICE'
This creates a billable EC2 server, encrypted disks, static IPv4 address, ECR,
Secrets Manager secret, backup bucket, network, and restricted IAM roles.
NOTICE
read -r -p 'Create/update these AWS resources? Type yes: ' confirm
[[ "$confirm" == yes ]] || exit 1
aws cloudformation deploy --region "$region" --stack-name "$stack" --template-file infra/stack.yaml \
  --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
  --parameter-overrides "GitHubRepository=$repository" "SourceCommit=$sha" "DomainName=$domain" "AdminEmail=$email" "ExistingGitHubOidcProviderArn=$provider"
aws cloudformation describe-stacks --region "$region" --stack-name "$stack" --query 'Stacks[0].Outputs' --output json > /tmp/saturday-club-outputs.json
python3 - <<'PY'
import json
raw={r['OutputKey']:r['OutputValue'] for r in json.load(open('/tmp/saturday-club-outputs.json'))}
values={key:raw[name] for key,name in {'AWS_REGION': 'AwsRegion', 'AWS_ROLE_ARN': 'DeploymentRoleArn', 'ECR_REPOSITORY': 'EcrRepository', 'EC2_INSTANCE_ID': 'InstanceId', 'DEPLOY_DOCUMENT': 'DeployDocumentName', 'APP_URL': 'AppUrl', 'PUBLIC_IP': 'PublicIpAddress', 'BACKUP_BUCKET': 'BackupBucketName', 'RUNTIME_SECRET_ARN': 'RuntimeSecretArn'}.items()}
print('\n1. Point the domain A record at:',values['PUBLIC_IP'])
print('2. Add these GitHub Actions repository variables (Settings > Secrets and variables > Actions > Variables):')
for key in ('AWS_REGION','AWS_ROLE_ARN','ECR_REPOSITORY','EC2_INSTANCE_ID','DEPLOY_DOCUMENT','APP_URL'):
    print(key+'='+values[key])
print('3. Wait for the instance to appear Online in Systems Manager and for DNS to resolve.')
print('4. Open GitHub Actions > Test and deploy > Run workflow on main.')
print('5. Retrieve the initial admin password privately from Secrets Manager:',values['RUNTIME_SECRET_ARN'])
print('Backup bucket:',values['BACKUP_BUCKET'])
PY
