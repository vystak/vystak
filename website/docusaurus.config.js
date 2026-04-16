// @ts-check
import {themes as prismThemes} from 'prism-react-renderer';

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'Vystak',
  tagline: 'Declarative AI agent orchestration',
  favicon: 'img/favicon.ico',

  url: 'https://vystak.dev',
  baseUrl: '/',
  trailingSlash: false,

  organizationName: 'vystak',
  projectName: 'vystak',

  onBrokenLinks: 'throw',
  onBrokenMarkdownLinks: 'warn',

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  headTags: [
    {
      tagName: 'link',
      attributes: { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
    },
    {
      tagName: 'link',
      attributes: { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: 'anonymous' },
    },
    {
      tagName: 'link',
      attributes: {
        rel: 'stylesheet',
        href: 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap',
      },
    },
  ],

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          sidebarPath: './sidebars.js',
          editUrl: 'https://github.com/vystak/vystak/tree/main/website/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      }),
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      navbar: {
        title: 'Vystak',
        logo: {
          alt: 'Vystak Logo',
          src: 'img/logo.svg',
        },
        items: [
          {
            type: 'docSidebar',
            sidebarId: 'docs',
            position: 'left',
            label: 'Docs',
          },
          {
            to: '/docs/examples/overview',
            label: 'Examples',
            position: 'left',
          },
          {
            to: '/blog',
            label: 'Blog',
            position: 'left',
          },
          {
            to: '/pricing',
            label: 'Pricing',
            position: 'left',
          },
          {
            href: 'https://pypi.org/project/vystak/',
            label: 'PyPI',
            position: 'right',
          },
          {
            href: 'https://www.npmjs.com/package/@vystak/core',
            label: 'npm',
            position: 'right',
          },
          {
            href: 'https://github.com/vystak/vystak',
            label: 'GitHub',
            position: 'right',
          },
        ],
      },
      footer: {
        style: 'dark',
        links: [
          {
            title: 'Docs',
            items: [
              {label: 'Getting Started', to: '/docs/getting-started/intro'},
              {label: 'CLI Reference', to: '/docs/cli/reference'},
            ],
          },
          {
            title: 'Community',
            items: [
              {label: 'GitHub', href: 'https://github.com/vystak/vystak'},
            ],
          },
        ],
        copyright: `Copyright © ${new Date().getFullYear()} ANKO Technologies Corp. Vystak is released under the Apache 2.0 License.`,
      },
      colorMode: {
        defaultMode: 'light',
        respectPrefersColorScheme: true,
      },
      prism: {
        theme: prismThemes.github,
        darkTheme: prismThemes.dracula,
        additionalLanguages: ['bash', 'yaml', 'python', 'json'],
      },
    }),
};

export default config;
