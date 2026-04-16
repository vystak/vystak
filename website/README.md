# Vystak Documentation

The Vystak documentation site, built with [Docusaurus 3](https://docusaurus.io/).

## Development

```bash
cd website
pnpm install
pnpm start
```

The site runs at `http://localhost:3000/AgentsStack/`.

## Build

```bash
pnpm build
```

The static site is generated in `website/build/`.

## Deployment

The site auto-deploys to GitHub Pages on push to `main` when `website/**` changes.
See `.github/workflows/deploy-docs.yml`.
