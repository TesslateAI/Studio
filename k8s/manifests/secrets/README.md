# Kubernetes Secrets Management

This directory contains templates for Kubernetes secrets. **Never commit actual secrets to git!**

## S3 Credentials Setup (Required for V3 Architecture)

The V3 architecture uses DigitalOcean Spaces (S3-compatible storage) for project hibernation/hydration.

### Option 1: Using kubectl (Recommended)

Create the secret directly from the command line:

```bash
kubectl create secret generic s3-credentials \
  --from-literal=S3_ACCESS_KEY_ID='YOUR_DO_SPACES_ACCESS_KEY' \
  --from-literal=S3_SECRET_ACCESS_KEY='YOUR_DO_SPACES_SECRET_KEY' \
  --from-literal=S3_BUCKET_NAME='tesslate-projects' \
  --from-literal=S3_ENDPOINT_URL='https://nyc3.digitaloceanspaces.com' \
  --from-literal=S3_REGION='us-east-1' \
  --namespace tesslate-user-environments
```

Replace:
- `YOUR_DO_SPACES_ACCESS_KEY`: Your DigitalOcean Spaces access key
- `YOUR_DO_SPACES_SECRET_KEY`: Your DigitalOcean Spaces secret key
- `tesslate-projects`: Your Spaces bucket name
- `nyc3.digitaloceanspaces.com`: Your Spaces endpoint (nyc3, sfo3, sgp1, etc.)

### Option 2: Using YAML File

1. Copy the template:
   ```bash
   cp s3-credentials.yaml.template s3-credentials.yaml
   ```

2. Base64 encode your credentials:
   ```bash
   echo -n 'YOUR_ACCESS_KEY' | base64
   echo -n 'YOUR_SECRET_KEY' | base64
   ```

3. Edit `s3-credentials.yaml` and replace the placeholder values

4. Apply to cluster:
   ```bash
   kubectl apply -f s3-credentials.yaml
   ```

5. **Delete the file** (it's in `.gitignore` but be safe):
   ```bash
   rm s3-credentials.yaml
   ```

## DigitalOcean Spaces Setup

### 1. Create Spaces Bucket

1. Log in to DigitalOcean
2. Go to Spaces Object Storage
3. Click "Create Space"
4. Choose region (same as your DOKS cluster for best performance)
5. Name: `tesslate-projects`
6. Enable CDN: No (not needed for private storage)
7. File Listing: Restricted (private bucket)

### 2. Generate Access Keys

1. Go to API → Spaces access keys
2. Click "Generate New Key"
3. Name: `tesslate-k8s-v3`
4. Save the Access Key ID and Secret Key securely
5. You won't be able to see the Secret Key again!

### 3. Configure CORS (Optional)

If you need to allow direct browser access to Spaces:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<CORSConfiguration>
  <CORSRule>
    <AllowedOrigin>https://studio-test.tesslate.com</AllowedOrigin>
    <AllowedMethod>GET</AllowedMethod>
    <AllowedMethod>PUT</AllowedMethod>
    <AllowedHeader>*</AllowedHeader>
    <MaxAgeSeconds>3000</MaxAgeSeconds>
  </CORSRule>
</CORSConfiguration>
```

### 4. Test Access

Verify the credentials work:

```bash
# Using AWS CLI (compatible with Spaces)
aws s3 ls s3://tesslate-projects \
  --endpoint-url https://nyc3.digitaloceanspaces.com \
  --region us-east-1
```

## Verify Secret in Cluster

Check if the secret was created successfully:

```bash
# List secrets
kubectl get secrets -n tesslate-user-environments

# Describe the secret (shows keys, not values)
kubectl describe secret s3-credentials -n tesslate-user-environments

# View the secret (base64 encoded)
kubectl get secret s3-credentials -n tesslate-user-environments -o yaml

# Decode a specific value (for debugging)
kubectl get secret s3-credentials -n tesslate-user-environments \
  -o jsonpath='{.data.S3_ACCESS_KEY_ID}' | base64 --decode
```

## Security Best Practices

1. **Never commit secrets to git** - Use `.gitignore` to exclude `*.yaml` (not `.template`)
2. **Rotate credentials regularly** - Update the secret every 90 days
3. **Use least privilege** - Give Spaces keys only the permissions needed:
   - `s3:GetObject` (download)
   - `s3:PutObject` (upload)
   - `s3:DeleteObject` (cleanup)
   - `s3:ListBucket` (check existence)
4. **Restrict bucket access** - Make sure the bucket is private (no public read)
5. **Monitor usage** - Set up alerts for unusual S3 API activity

## Updating the Secret

To update the secret with new credentials:

```bash
# Delete old secret
kubectl delete secret s3-credentials -n tesslate-user-environments

# Create new secret (Option 1 above)
kubectl create secret generic s3-credentials ...
```

Or use `kubectl patch`:

```bash
kubectl patch secret s3-credentials -n tesslate-user-environments \
  --type='json' \
  -p='[{"op": "replace", "path": "/data/S3_ACCESS_KEY_ID", "value": "'"$(echo -n 'NEW_KEY' | base64)"'"}]'
```

## Troubleshooting

### Init Container Fails with "Access Denied"

Check:
1. Credentials are correct (decode and test with AWS CLI)
2. Bucket name matches
3. Endpoint URL is correct
4. Spaces keys have proper permissions

### Pods Can't Read Secret

Check:
1. Secret exists in the correct namespace
2. Secret name matches in deployment manifest (`s3-credentials`)
3. ServiceAccount has permission to read secrets (should be default)

### S3 Upload Timeout

The `terminationGracePeriodSeconds` in the deployment is set to 120s. If projects are very large:
1. Consider excluding `node_modules` from the zip
2. Increase the grace period to 180s or 300s
3. Check network bandwidth to Spaces
