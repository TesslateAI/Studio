# Google OAuth Setup Guide

This guide will walk you through setting up Google OAuth authentication for Tesslate Studio.

## Prerequisites

- A Google account
- Access to [Google Cloud Console](https://console.cloud.google.com)

## Step 1: Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Click the project dropdown at the top of the page
3. Click **"New Project"**
4. Enter a project name (e.g., "Tesslate Studio Auth")
5. Click **"Create"**

## Step 2: Enable Google+ API

1. In your Google Cloud Console, navigate to **"APIs & Services" → "Library"**
2. Search for **"Google+ API"**
3. Click on it and press **"Enable"**

Alternatively, enable the **"Google Identity"** API which is the modern replacement.

## Step 3: Configure OAuth Consent Screen

1. Navigate to **"APIs & Services" → "OAuth consent screen"**
2. Select **"External"** user type (unless you have a Google Workspace organization)
3. Click **"Create"**

### Fill in the required information:

**App Information:**
- **App name**: Tesslate Studio (or your custom name)
- **User support email**: Your email address
- **App logo**: (Optional) Upload your logo

**App Domain:**
- **Application home page**: `http://localhost` (for local dev) or your production URL
- **Application privacy policy link**: (Optional, but recommended for production)
- **Application terms of service link**: (Optional, but recommended for production)

**Developer contact information:**
- Your email address

4. Click **"Save and Continue"**

### Scopes (Step 2 of consent screen):

5. Click **"Add or Remove Scopes"**
6. Select these scopes:
   - `.../auth/userinfo.email` - See your email address
   - `.../auth/userinfo.profile` - See your personal info
   - `openid` - Associate you with your personal info
7. Click **"Update"** then **"Save and Continue"**

### Test Users (if app is not published):

8. Add test users (your email) if the app is in testing mode
9. Click **"Save and Continue"**

## Step 4: Create OAuth Credentials

1. Navigate to **"APIs & Services" → "Credentials"**
2. Click **"+ CREATE CREDENTIALS"** → **"OAuth client ID"**
3. Select **"Web application"** as the application type
4. Enter a name: **"Tesslate Studio Web Client"**

### Configure authorized origins:

Add these **Authorized JavaScript origins**:
```
http://localhost:5173
http://localhost
http://localhost:80
```

For production, also add:
```
https://yourdomain.com
```

### Configure redirect URIs:

Add these **Authorized redirect URIs**:
```
http://localhost/auth/google/callback
http://localhost:5173/auth/google/callback
```

For production, also add:
```
https://yourdomain.com/auth/google/callback
```

5. Click **"Create"**

## Step 5: Copy Credentials to .env

You'll see a modal with your credentials:

- **Client ID**: Starts with something like `123456789-abc.apps.googleusercontent.com`
- **Client Secret**: A random string

Copy these values and add them to your `.env` file:

```bash
# Google OAuth Configuration
GOOGLE_CLIENT_ID=123456789-abc.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret-here
GOOGLE_OAUTH_REDIRECT_URI=http://localhost/auth/google/callback
```

**Important Notes:**
- Keep your Client Secret secure and never commit it to version control
- Update the redirect URI to match your production domain when deploying
- In local development, use `http://localhost` to match your APP_DOMAIN setting

## Step 6: Test the OAuth Flow

1. Restart your backend server to load the new environment variables:
   ```bash
   docker compose restart orchestrator
   ```

2. Open your browser to `http://localhost`
3. Click "Sign in with Google"
4. You should be redirected to Google's OAuth consent screen
5. After granting permissions, you'll be redirected back to your app and logged in

## Troubleshooting

### "Error 400: redirect_uri_mismatch"

This means the redirect URI in your request doesn't match what you configured in Google Cloud Console.

**Solution:**
1. Check your `.env` file: `GOOGLE_OAUTH_REDIRECT_URI` should match the authorized redirect URI
2. Make sure the URI in Google Cloud Console matches exactly (including http/https, port, path)
3. Common mistake: forgetting the `/auth/google/callback` path

### "Error 403: access_denied"

This usually means:
1. Your app is in testing mode and the user is not added as a test user
2. The OAuth consent screen is not properly configured

**Solution:**
1. Add yourself as a test user in the OAuth consent screen
2. Or publish your app (not recommended for internal tools)

### "OAuth client not found" or "Invalid client"

**Solution:**
1. Make sure you copied the correct Client ID and Secret
2. Verify there are no extra spaces or line breaks in your `.env` file
3. Restart your backend after updating environment variables

## Production Considerations

When deploying to production:

1. **Update redirect URIs** to use your production domain:
   ```bash
   GOOGLE_OAUTH_REDIRECT_URI=https://yourdomain.com/auth/google/callback
   ```

2. **Add production domains** to authorized origins and redirect URIs in Google Cloud Console

3. **Enable HTTPS** by setting:
   ```bash
   COOKIE_SECURE=true
   ```

4. **Consider publishing your OAuth app** if you want it available to all Google users:
   - Go to OAuth consent screen
   - Click "Publish App"
   - Note: This may require verification if you request sensitive scopes

5. **Set up proper error handling** and logging for OAuth failures

## Security Best Practices

- **Never commit** `.env` files with real credentials to version control
- **Rotate secrets regularly** (regenerate Client Secret every 6-12 months)
- **Use separate OAuth clients** for development and production
- **Monitor OAuth usage** in Google Cloud Console for suspicious activity
- **Enable 2FA** on your Google Cloud Console account

## Optional: Multiple Environments

For better security, create separate OAuth clients for different environments:

### Development OAuth Client:
- Authorized origins: `http://localhost:5173`, `http://localhost`
- Redirect URI: `http://localhost/auth/google/callback`

### Production OAuth Client:
- Authorized origins: `https://yourdomain.com`
- Redirect URI: `https://yourdomain.com/auth/google/callback`

Store credentials in different `.env` files:
- `.env.local` for development
- `.env.production` for production deployment

## Need Help?

- [Google OAuth 2.0 Documentation](https://developers.google.com/identity/protocols/oauth2)
- [Google Cloud Console](https://console.cloud.google.com)
- [fastapi-users OAuth Documentation](https://fastapi-users.github.io/fastapi-users/configuration/oauth/)
