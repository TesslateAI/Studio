# GitHub OAuth Setup Guide

This guide will help you set up GitHub OAuth authentication for Tesslate Studio.

## Prerequisites

- A GitHub account
- Tesslate Studio running locally or in production

## Step 1: Create a GitHub OAuth App

1. Go to GitHub Settings: https://github.com/settings/applications/new
2. Fill in the application details:

### For Local Development:
- **Application name**: `Tesslate Studio Dev`
- **Homepage URL**: `http://localhost:5173`
- **Application description**: (optional) `Local development instance of Tesslate Studio`
- **Authorization callback URL**: `http://localhost:5173/auth/github/callback`

### For Production:
- **Application name**: `Tesslate Studio`
- **Homepage URL**: `https://your-domain.com`
- **Application description**: (optional) `AI-powered development studio`
- **Authorization callback URL**: `https://your-domain.com/auth/github/callback`

3. Click **"Register application"**

## Step 2: Get Your OAuth Credentials

After creating the app, you'll see:
- **Client ID**: A public identifier for your app
- **Client Secret**: Click "Generate a new client secret" and copy it immediately

⚠️ **Important**: Store the Client Secret securely - you won't be able to see it again!

## Step 3: Configure Environment Variables

Edit your `orchestrator/.env` file and add:

```env
# GitHub OAuth Configuration
GITHUB_CLIENT_ID=your_client_id_here
GITHUB_CLIENT_SECRET=your_client_secret_here
GITHUB_OAUTH_REDIRECT_URI=http://localhost:5173/auth/github/callback
```

For production, update the redirect URI:
```env
GITHUB_OAUTH_REDIRECT_URI=https://your-domain.com/auth/github/callback
```

## Step 4: Restart Services

```bash
# Stop services
docker-compose down

# Rebuild and start with new configuration
docker-compose up --build
```

## Step 5: Test the Integration

1. Navigate to your Tesslate Studio instance
2. Go to a project or the dashboard
3. Click on the GitHub panel
4. Click "Connect GitHub"
5. You'll be redirected to GitHub to authorize the app
6. After authorization, you'll be redirected back to Tesslate Studio
7. You should see your GitHub username confirming the connection

## OAuth Scopes

Tesslate Studio requests the following OAuth scopes:
- `repo` - Full control of private repositories (required for cloning, pushing, pulling)
- `user:email` - Access user email addresses (for identification)

## Security Notes

- **Never commit** your `.env` file with real credentials
- **Client Secret** should be kept confidential
- Users can revoke access anytime from: https://github.com/settings/applications
- OAuth tokens are encrypted at rest in the database
- No tokens are ever exposed to the frontend

## Troubleshooting

### "Invalid OAuth state" error
- OAuth states expire after 10 minutes
- Try connecting again

### "GitHub not connected" error
- Ensure environment variables are set correctly
- Check that the OAuth app is active on GitHub
- Verify the redirect URI matches exactly

### Cannot see private repositories
- Ensure the OAuth app has the `repo` scope
- User may need to grant access to specific organizations

## Revoking Access

Users can revoke Tesslate Studio's access:
1. Go to: https://github.com/settings/applications
2. Find "Tesslate Studio" in the list
3. Click "Revoke access"

## Support

For issues or questions, please open an issue on the Tesslate Studio repository.