# Tesslate Studio Architecture Diagrams

This directory contains Mermaid diagram files that visualize the Tesslate Studio architecture and key workflows.

## Diagram Files

### 1. high-level-architecture.mmd
**Type:** System Architecture Diagram (Graph)

**Description:** Complete system overview showing all major components and their connections:
- Client layer (Web Browser)
- Frontend layer (React 19 + Vite + TypeScript with Monaco Editor, Chat UI, XYFlow)
- Backend layer (FastAPI routers, services, agent system)
- Data layer (PostgreSQL, S3/MinIO)
- External services (LiteLLM, AI providers, Stripe, OAuth, deployment platforms)
- Container orchestration (Docker Compose for dev, Kubernetes for production)
- User project namespaces with isolated resources

**Use this diagram to:** Understand the overall system architecture and how components interact.

---

### 2. request-flow.mmd
**Type:** Sequence Diagram

**Description:** Shows the complete request lifecycle through the system:
- Standard HTTP request flow with authentication
- WebSocket streaming flow for agent chat
- Server-Sent Events (SSE) flow for real-time task updates
- Authentication check at middleware layer
- Response handling and UI updates

**Use this diagram to:** Understand how user requests flow through the system and how real-time features work.

---

### 3. agent-execution.mmd
**Type:** Flowchart

**Description:** Detailed agent execution workflow showing:
- Agent creation from MarketplaceAgent models
- System prompt and tool configuration
- LLM streaming calls via LiteLLM
- Tool extraction and execution loop
- Approval flow for dangerous operations (bash commands)
- Different agent strategies (StreamAgent, IterativeAgent, ReActAgent)
- Error handling and iteration limits

**Use this diagram to:** Understand how AI agents process user requests and execute tools.

---

### 4. container-lifecycle.mmd
**Type:** State Diagram

**Description:** Container and project lifecycle states:
- Project creation and namespace setup
- Container states: Stopped → Starting → Running → Failed
- Init container hydration process (S3 → PVC)
- File manager pod (always running)
- Container connections (ENV_INJECTION, HTTP_API, DATABASE)
- Dehydration and cleanup process (PVC → S3)
- Ingress creation for traffic routing
- Project deletion cascade

**Use this diagram to:** Understand container orchestration and state transitions.

---

### 5. s3-sandwich.mmd
**Type:** Sequence Diagram

**Description:** The S3 Sandwich pattern for project storage:
- **Layer 1 - Hydration:** S3 download → Init container → PVC mount
- **Layer 2 - Runtime:** Fast local I/O on Persistent Volume Claim
- **Layer 3 - Dehydration:** PreStop hook → S3 upload before termination
- Cleanup cronjob for idle project detection
- Benefits: Fast runtime I/O, cost-effective storage, stateless pods

**Use this diagram to:** Understand project persistence and the ephemeral storage strategy.

---

### 6. auth-flow.mmd
**Type:** Flowchart

**Description:** Authentication and authorization flows:
- JWT Bearer token flow (email/password login)
- OAuth flow (GitHub, Google) with callback handling
- Cookie-based session management
- CSRF token validation for state-changing requests
- Token refresh mechanism
- Permission checks and role-based access control
- Logout process

**Use this diagram to:** Understand user authentication methods and security patterns.

---

### 7. deployment-pipeline.mmd
**Type:** Flowchart

**Description:** Deployment workflows for different environments:
- **Minikube (Local):** Build → Delete old image → Load to Minikube → Force pod restart
- **AWS EKS (Production):** Build → Tag → Push to ECR → Delete pod → Restart Ingress
- Image pull policies (Never for Minikube, Always for EKS)
- Critical requirement for `--no-cache` flag to prevent layer caching issues
- Pod deletion to force fresh image pulls
- Verification and monitoring steps

**Use this diagram to:** Understand the deployment process and troubleshoot image update issues.

---

## Viewing the Diagrams

These diagrams use [Mermaid](https://mermaid.js.org/) syntax and can be viewed in:

1. **GitHub/GitLab:** Automatically rendered in markdown files
2. **VS Code:** Install the "Markdown Preview Mermaid Support" extension
3. **Mermaid Live Editor:** https://mermaid.live/
4. **Documentation sites:** MkDocs, Docusaurus, etc. with Mermaid plugins

## Rendering Example

To embed in markdown:

\`\`\`markdown
\`\`\`mermaid
{{file-contents}}
\`\`\`
\`\`\`

Or reference the file directly in some documentation tools:

\`\`\`markdown
!include diagrams/high-level-architecture.mmd
\`\`\`

## Maintenance

When updating these diagrams:
- Keep syntax valid using the Mermaid Live Editor
- Update this README if diagram purpose changes
- Ensure diagrams reflect current system architecture
- Add notes for critical details that developers should know

## Related Documentation

- `docs/architecture/` - Architecture documentation
- `CLAUDE.md` - System overview and development guide
- `k8s/ARCHITECTURE.md` - Kubernetes-specific architecture details
