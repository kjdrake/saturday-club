# Invitations, Google/Facebook sign-in, and invitation email

Existing email/password accounts and invitation codes continue to work. Commissioner tools can create a single-use invitation link or send one through SES. Text invitation opens your phone's SMS composer; you choose the recipient and tap Send. No AWS SMS number or subscription is used. Links expire after seven days and are consumed only after successful account creation. Treat them like passwords: anyone holding an unused link can join. Invites are bearer invitations, not locked to the delivery email address; a friend may use a different Google/Facebook email.

New social accounts always require an invitation. Existing members first sign in normally, open their profile, and choose **Connect Google** or **Connect Facebook**. This explicitly connects to their existing picks, commissioner role, and standings. Matching email addresses never silently merge accounts. Disabling a member also prevents social sign-in. Provider tokens are used server-side and discarded.

## One-time update for this existing AWS installation

The original host deployment script only passes the original four secret fields to Docker. Merely adding new fields to Secrets Manager will not enable these features until the deployer is refreshed.

From AWS CloudShell, in a fresh clone/checkout of the reviewed `main` branch:

```sh
git pull --ff-only
python3 infra/account_services.py plan --region us-east-1 --stack saturday-club-prod
```

Open **CloudFormation → saturday-club-prod → Change sets**. Review and execute the new change set. Expected changes are the instance role's `ses:SendEmail` permission scoped to your domain identity and a metadata hop limit of 2 so the container can obtain short-lived instance-role credentials. Other existing parameters are preserved. Stop and inspect if replacements are proposed. Wait for **UPDATE_COMPLETE**. This does not register provider apps, verify SES, modify DNS, or buy a number.

Then refresh the existing host deployment script:

```sh
python3 infra/account_services.py refresh-deployer --region us-east-1 --stack saturday-club-prod
```

Wait for the printed command to succeed in **Systems Manager → Run Command**. After configuring the runtime secret below, run **GitHub → Actions → Test and deploy → Run workflow → main**. New installations use the updated deployer automatically.

## Runtime settings

In **AWS Secrets Manager**, open the secret named in the stack's `RuntimeSecretArn` output. Choose **Retrieve secret value → Edit**. Preserve existing admin/password/odds fields. Add these key/value pairs, independently enabling whichever services you configure:

| Key | Value |
| --- | --- |
| `APP_URL` | `https://4thandsoul.com` |
| `GOOGLE_CLIENT_ID` | Google web OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google web OAuth client secret |
| `FACEBOOK_CLIENT_ID` | Meta app ID |
| `FACEBOOK_CLIENT_SECRET` | Meta app secret |
| `SES_FROM_EMAIL` | `invitations@4thandsoul.com` |

Do not place secrets in GitHub Actions variables, public code, screenshots, or chat. The AWS region is supplied by the production Compose configuration. Re-run the GitHub deployment after changing secrets. Unconfigured social providers are hidden. Email requests show a clear setup error if sender/base URL is missing; copying links and texting still work.

## Google

In [Google Auth Platform](https://console.cloud.google.com/auth/overview), create/configure an external app and OAuth client with application type **Web application**. Use Saturday Club by 4th & Soul for branding and `4thandsoul.com` as the authorized domain. Configure the requested support/developer contacts.

Authorized redirect URI, exactly:

```
https://4thandsoul.com/api/oauth/google/callback
```

The integration requests only `openid email`, using the authorization-code flow with PKCE. Add the client ID/secret to the runtime secret. While in testing, add your friends as test users; publish the app for broader use and complete any verification Google requests. Privacy policy: `https://4thandsoul.com/privacy.html`.

## Facebook

In [Meta for Developers](https://developers.facebook.com/apps/), create an app supporting **Facebook Login** for a website. Set the site URL to `https://4thandsoul.com`, enable web OAuth login and strict redirect URI matching, and add this valid OAuth redirect URI exactly:

```
https://4thandsoul.com/api/oauth/facebook/callback
```

Set the app domain to `4thandsoul.com`, privacy policy to `https://4thandsoul.com/privacy.html`, and user-data deletion instructions URL to `https://4thandsoul.com/privacy.html#deletion`. Add the app ID/secret to the runtime secret. Complete Meta's requested verification/access review and switch to Live for friends outside app roles. The adapter pins Graph API `v23.0`; upgrade it before Meta retires that version.

Facebook must share an email to create a new league account. Existing signed-in members can connect a provider without replacing their league email. Accounts are identified by provider and stable provider user ID, never by a browser-supplied email or profile.

## Automatic invitation and password-reset email through SES

1. In **Amazon SES**, select **us-east-1 → Verified identities → Create identity → Domain**, using `4thandsoul.com`. Enable DKIM. Use SES's Route 53 publishing option or add its supplied DKIM records in your public hosted zone. Wait for the identity to show Verified. These records do not replace the website's A record.
2. On **SES → Account dashboard**, request production access if the account is in the sandbox. Explain the low-volume, commissioner-triggered invitations for a private friends league. Until approved, SES only sends to verified recipients (or its mailbox simulator).
3. Use the Essentials or à-la-carte plan; a paid Pro plan or dedicated IP is unnecessary for this volume. Set `SES_FROM_EMAIL=invitations@4thandsoul.com` in the runtime secret. The infrastructure grants sending only from your domain identity; no AWS access keys are needed.
4. Apply the stack/deployer update above and redeploy. In commissioner tools, enter a friend's name, choose **Send email automatically**, enter the recipient email, and click **Create invitation**. Success means SES accepted the message, not guaranteed inbox delivery. Configure SES bounce/complaint monitoring and check the account dashboard if delivery fails.
5. Test first with an address you control. Open the invitation in a private browser window, check that its code is prefilled, and complete one sign-up. Reusing the link must fail. Test real Google/Facebook sign-in after their credentials are installed; automated tests mock the external providers and do not prove that provider-console settings are correct.

An email-send error cancels that invitation, leaving no active unconfirmed link. Requests are restricted to commissioners and rate-limited. Link-only invitations and prefilled texts remain available if SES is unavailable. The application does not retain the recipient's email before registration or promise delivery receipts.

## Password reset emails

The same SES identity, instance-role permission and runtime settings send password-reset email. No new AWS credentials or sender setup is required. After deployment, test **Sign in → Forgot password?** with an address you control, then open the email and choose a new password. Links expire after 30 minutes, work once, and revoke existing sessions on success. The request response is intentionally identical for unknown, disabled and active accounts; it does not guarantee inbox delivery. In the SES sandbox the recipient still must be verified. See [security operations](security.md) for details and operator recovery.
