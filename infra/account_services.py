#!/usr/bin/env python3
"""Prepare the account-services stack change or refresh the existing host deployer.
Run in authenticated AWS CloudShell from a reviewed checkout of main.
Never reads or prints runtime secret values.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]

def aws(region, *args):
    return json.loads(subprocess.check_output(['aws', '--region', region, *args, '--output', 'json'], text=True))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['plan','refresh-deployer'])
    parser.add_argument('--region',default='us-east-1')
    parser.add_argument('--stack',default='saturday-club-prod')
    args=parser.parse_args()
    stack=aws(args.region,'cloudformation','describe-stacks','--stack-name',args.stack)['Stacks'][0]
    if args.action=='plan':
        # Preserve every existing parameter, including bootstrap commit and admin email.
        parameters=[{'ParameterKey':p['ParameterKey'],'UsePreviousValue':True} for p in stack['Parameters']]
        change=aws(args.region,'cloudformation','create-change-set','--stack-name',args.stack,'--change-set-name','account-services-'+str(int(time.time())),
                   '--template-body','file://'+str(ROOT/'infra/stack.yaml'),'--capabilities','CAPABILITY_IAM','--parameters',json.dumps(parameters))
        print('Change set created:',change['Id'])
        print('Review CloudFormation > your stack > Change sets. Expected changes: runtime-role SES permission and instance metadata hop limit. No resource replacement is intended.')
        print('Execute only after reviewing the change set, then wait for UPDATE_COMPLETE. This does not register domains, purchase SMS numbers, or change DNS.')
    else:
        sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        if not re.fullmatch('[0-9a-f]{40}',sha):raise SystemExit('Invalid source commit')
        instance=next(o['OutputValue'] for o in stack['Outputs'] if o['OutputKey']=='InstanceId')
        commands=['set -eu',f'curl -fsSL --retry 3 https://raw.githubusercontent.com/kjdrake/saturday-club/{sha}/infra/deploy.sh -o /tmp/saturday-club-deploy.sh',
                  'bash -n /tmp/saturday-club-deploy.sh','install -m 700 /tmp/saturday-club-deploy.sh /opt/saturday-club/deploy.sh','rm /tmp/saturday-club-deploy.sh']
        result=aws(args.region,'ssm','send-command','--instance-ids',instance,'--document-name','AWS-RunShellScript','--parameters',json.dumps({'commands':commands}))
        print('Deployer refresh command:',result['Command']['CommandId'])
        print('Wait for Success in Systems Manager > Run Command, then run the GitHub Test and deploy workflow on main to apply the updated runtime secret.')

if __name__=='__main__':main()
