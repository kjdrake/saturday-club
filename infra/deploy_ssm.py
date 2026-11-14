"""Submit one versioned SSM deployment and wait for its health-check/rollback result."""
import json
import os
import subprocess
import time

def aws(*args):
    result = subprocess.run(['aws', *args, '--output', 'json'], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)

def main():
    instance = os.environ['INSTANCE_ID']
    sent = aws('ssm', 'send-command', '--instance-ids', instance,
               '--document-name', os.environ['DEPLOY_DOCUMENT'],
               '--parameters', json.dumps({'ImageTag': [os.environ['IMAGE_TAG']]}),
               '--timeout-seconds', '900')
    command = sent['Command']['CommandId']
    print('SSM deployment command:', command, flush=True)
    for _ in range(160):
        time.sleep(5)
        try:
            state = aws('ssm', 'get-command-invocation', '--command-id', command, '--instance-id', instance)
        except subprocess.CalledProcessError as error:
            if 'InvocationDoesNotExist' in error.stderr:
                continue
            raise
        if state['Status'] in ('Pending', 'InProgress', 'Delayed'):
            continue
        # Deployment scripts never print runtime secret values.
        print(state.get('StandardOutputContent', ''))
        print(state.get('StandardErrorContent', ''))
        if state['Status'] != 'Success':
            raise SystemExit('Deployment failed; see the SSM output above for rollback status.')
        return
    raise SystemExit('Timed out waiting for SSM. Check the command before starting another deployment.')

if __name__ == '__main__':
    main()
