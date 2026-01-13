## How to Get a Slack Webhook URL

To receive crash alerts, you need a Slack Webhook. If you don't have a Slack account, you will need to create a free workspace first.

### 1. Prepare your Slack Workspace
1.  Open your Slack Workspace.
2.  Create a new channel where you want the alerts to go (e.g., `#gpu-alerts` or `#server-monitor`).

### 2. Create the App
1.  Go to [api.slack.com/apps](https://api.slack.com/apps).
2.  Click the **Create New App** button.
3.  Select **From scratch**.
4.  **App Name:** Enter `GPU Monitor` (or whatever you prefer).
5.  **Pick a workspace:** Select your workspace from the dropdown.
6.  Click **Create App**.

### 3. Enable Webhooks
1.  In the left sidebar, under **Features**, click **Incoming Webhooks**.
2.  Switch the toggle **Activate Incoming Webhooks** to **On**.

### 4. Create the Webhook URL
1.  Scroll down to the bottom of the page and click **Add New Webhook to Workspace**.
2.  Slack will ask for permission. Select the channel you created in Step 1 (e.g., `#gpu-alerts`).
3.  Click **Allow**.

### 5. Copy the URL
1.  You will be redirected back to the app settings.
2.  Look for the **Webhook URL** (it starts with `https://hooks.slack.com/services/...`).
3.  Click **Copy**.

### 6. Add to Configuration
Paste this URL into your `.env` file:
```bash
SLACK_WEBHOOK_URL= ''