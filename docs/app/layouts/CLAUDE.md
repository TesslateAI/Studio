# Layouts

Page-layout wrappers in `app/src/layouts/`.

## File Index

| File | Purpose |
|------|---------|
| `layouts/SettingsLayout.tsx` | Two-column settings layout. Collapsible desktop sidebar (`SettingsSidebar`), mobile drawer with spring animation, route-based titles, safe-area support for notched devices |
| `layouts/MarketplaceLayout.tsx` | Adaptive layout: authenticated users get `NavigationSidebar` + outlet; public users get `PublicMarketplaceHeader` + outlet + `PublicMarketplaceFooter`. Non-blocking auth check, provides `MarketplaceAuthContext` to children |
| `layouts/PublicMarketplaceHeader.tsx` | Public marketplace header: logo, Explore/Agents/Templates links, theme toggle, Sign In / Sign Up. Mobile hamburger menu |
| `layouts/PublicMarketplaceFooter.tsx` | SEO-friendly footer with category links, company links, Sign Up CTA, copyright. Uses native `<a>` tags (not Links) for crawler friendliness |

## Router Integration

```tsx
<Route path="/settings" element={<SettingsLayout />}>
  <Route index element={<Navigate to="/settings/profile" replace />} />
  <Route path="profile" element={<ProfileSettings />} />
  <Route path="preferences" element={<PreferencesSettings />} />
  ...
</Route>

<Route element={<MarketplaceLayout />}>
  <Route path="/marketplace" element={<Marketplace />} />
  <Route path="/marketplace/:slug" element={<MarketplaceDetail />} />
  <Route path="/marketplace/browse/:type" element={<MarketplaceBrowse />} />
  <Route path="/marketplace/author/:username" element={<MarketplaceAuthor />} />
</Route>
```

## Auth States in MarketplaceLayout

| Auth State | View |
|------------|------|
| `loading` | Public (public view renders immediately to avoid SEO/perf penalty) |
| `unauthenticated` | Public |
| `authenticated` | `NavigationSidebar` + outlet |

The loading state intentionally shows the public view so:
1. Crawlers get content immediately
2. No blocking render / visible spinner
3. Instant perceived load for all users

## Mobile Drawer Pattern

`SettingsLayout` uses Framer Motion spring animation:

```tsx
<motion.div
  initial={{ x: '-100%' }}
  animate={{ x: 0 }}
  exit={{ x: '-100%' }}
  transition={{ type: 'spring', stiffness: 400, damping: 30 }}
  className="w-[70vw] max-w-[240px] min-w-[180px]"
>
  <SettingsSidebarMobile onClose={handleCloseMobileMenu} />
</motion.div>
```

## Best Practices

1. Non-blocking auth checks: never spinner-gate the marketplace.
2. Minimum 44x44px touch targets on mobile controls.
3. Support notched devices: `pt-[env(safe-area-inset-top)]`.
4. Theme-aware styling via CSS custom properties, not hardcoded Tailwind colors.
5. Provider-scope context (like `MarketplaceAuthContext`) wraps the entire layout output.

## Related Docs

- `docs/app/contexts/CLAUDE.md` – MarketplaceAuthContext
- `docs/app/components/settings.md` – settings primitives rendered inside `SettingsLayout`
- `docs/app/components/ui/CLAUDE.md` – `NavigationSidebar` used in both layouts
