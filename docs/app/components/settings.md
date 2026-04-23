# Settings Components

Reusable primitives for settings pages in `app/src/components/settings/`. Every page under `/settings/*` composes these.

## File Index

| File | Purpose |
|------|---------|
| `settings/index.ts` | Barrel export |
| `settings/SettingsSection.tsx` | Top-level wrapper with title and description; ensures consistent spacing and max-width |
| `settings/SettingsGroup.tsx` | Container for related settings items (e.g., "Personal Information"). Collapsible and labeled |
| `settings/SettingsItem.tsx` | Single row: label, description, control area on the right |
| `settings/SettingsSidebar.tsx` | Left navigation linking the seven settings pages; desktop and mobile variants |
| `settings/CustomProviderComponents.tsx` | Provider-specific credential forms used inside `DeploymentSettings` (Vercel, Netlify, Cloudflare, Amplify, custom S3) |

## Composition

```tsx
<SettingsSection title="Profile" description="Public information displayed on your account">
  <SettingsGroup label="Personal Information">
    <SettingsItem label="Display Name" description="Shown on your profile">
      <Input value={name} onChange={setName} />
    </SettingsItem>
    <SettingsItem label="Email">
      <Input value={email} disabled />
    </SettingsItem>
  </SettingsGroup>
  <SettingsGroup label="Avatar">
    <SettingsItem label="Profile Picture">
      <ImageUpload />
    </SettingsItem>
  </SettingsGroup>
</SettingsSection>
```

## Related Docs

- `docs/app/pages/settings.md` – modular settings page architecture
- `docs/app/layouts/CLAUDE.md` – `SettingsLayout` two-column layout
