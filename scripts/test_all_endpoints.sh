#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "Testing All Tesslate Studio Endpoints..."
echo "========================================="

# Function to test endpoint
test_endpoint() {
    local url=$1
    local description=$2
    local auth=$3

    if [ "$auth" = "yes" ]; then
        response=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$url")
    else
        response=$(curl -s -o /dev/null -w "%{http_code}" "$url")
    fi

    if [ "$response" = "200" ]; then
        echo -e "${GREEN}✓${NC} $description: $url (Status: $response)"
    else
        echo -e "${RED}✗${NC} $description: $url (Status: $response)"
    fi
}

# Get auth token
echo "Getting auth token..."
TOKEN=$(curl -s -X POST http://studio.localhost/api/auth/token \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=a&password=aaaaaa" | jq -r '.access_token')

if [ "$TOKEN" = "null" ] || [ -z "$TOKEN" ]; then
    echo -e "${RED}Failed to get auth token${NC}"
    exit 1
fi

echo -e "${GREEN}Got auth token${NC}"
echo ""

# Test public endpoints
echo "Testing Public Endpoints:"
test_endpoint "http://studio.localhost" "Frontend App" "no"
test_endpoint "http://api.localhost/" "API Root" "no"
test_endpoint "http://api.localhost/health" "API Health" "no"

echo ""
echo "Testing Authenticated Endpoints:"
# Test authenticated endpoints
test_endpoint "http://studio.localhost/api/projects/" "Projects List" "yes"
test_endpoint "http://studio.localhost/api/marketplace/agents" "Marketplace Agents" "yes"
test_endpoint "http://studio.localhost/api/admin/metrics/summary" "Admin Metrics" "yes"
test_endpoint "http://studio.localhost/api/agents" "Agents List" "yes"
test_endpoint "http://studio.localhost/api/github/status" "GitHub Status" "yes"

echo ""
echo "Testing Frontend Routes (should all return 200 with HTML):"
test_endpoint "http://studio.localhost/dashboard" "Dashboard Page" "no"
test_endpoint "http://studio.localhost/marketplace" "Marketplace Page" "no"
test_endpoint "http://studio.localhost/admin" "Admin Page" "no"
test_endpoint "http://studio.localhost/login" "Login Page" "no"
test_endpoint "http://studio.localhost/register" "Register Page" "no"

echo ""
echo "========================================="
echo "Testing Complete!"