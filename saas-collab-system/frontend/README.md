# Frontend

Vue 3 + Vite frontend for the SaaS collaboration system.

## Install Dependencies

```powershell
cd saas-collab-system/frontend
npm.cmd install
```

Use `npm.cmd` on Windows PowerShell if `npm` is blocked by script execution policy.

## Start Development Server

```powershell
npm.cmd run dev
```

Default local URL:

```text
http://127.0.0.1:5173/
```

## Mock Mode

The frontend currently uses mock data for stage 0 pages.

- Login uses a mock user from `src/mock/currentUser.js`.
- Business pages use page-local mock data.
- API files under `src/api/` return mock-style responses or method placeholders.
- No real backend request is required for current page previews.

## Environment Variables

Copy `.env.example` if local overrides are needed.

```text
VITE_API_BASE_URL=/api
VITE_USE_MOCK=true
```

Variables:

- `VITE_API_BASE_URL`: base URL used by the axios request wrapper.
- `VITE_USE_MOCK`: mock mode switch. Current default is `true`.

Do not write real tokens, passwords, cookies, or API keys into frontend environment files.

## Page Directory

Main page files live under `src/views/`:

- `auth/`: login page.
- `dashboard/`: dashboard placeholder.
- `products/`: research, product master data, and product status pages.
- `purchasing/`: purchase order pages.
- `suppliers/`: supplier task and shipment pages.
- `listings/`: multi-country listing profile and template pages.
- `pricing/`: price list and price detail pages.
- `rpa/`: RPA task center pages.
- `integrations/`: API sync task and log pages.
- `finance/`: finance import placeholder.
- `reports/`: basic report placeholder.
- `audit/`: operation log page.

Shared layout and UI helpers:

- `src/layouts/MainLayout.vue`: backend-style application shell.
- `src/components/MvpPage.vue`: generic MVP placeholder list component.
- `src/router/index.js`: route and menu configuration.
- `src/stores/`: Pinia stores.

## API Wrapper

Axios is configured in `src/api/request.js`.

- `baseURL` reads from `VITE_API_BASE_URL`.
- `VITE_USE_MOCK` controls the mock mode flag.
- Module API files live in `src/api/`, including `auth.js`, `products.js`, `purchasing.js`, `suppliers.js`, `listings.js`, `pricing.js`, `rpa.js`, `integrations.js`, and `audit.js`.

Current rule: do not connect to real backend APIs until the corresponding backend endpoints are confirmed.
