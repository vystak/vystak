// @ts-check

/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  docs: [
    {
      type: 'category',
      label: 'Getting Started',
      collapsed: false,
      items: [
        'getting-started/intro',
        'getting-started/installation',
        'getting-started/quickstart',
      ],
    },
    {
      type: 'category',
      label: 'Concepts',
      items: [
        'concepts/agents',
        'concepts/models',
        'concepts/providers-and-platforms',
        'concepts/transport',
        'concepts/services',
        'concepts/channels',
      ],
    },
    {
      type: 'category',
      label: 'Channels',
      items: [
        'channels/overview',
        'channels/slack',
        'channels/chat',
      ],
    },
    {
      type: 'category',
      label: 'Deploying',
      items: [
        'deploying/docker',
        'deploying/azure',
        'deploying/environments',
        'deploying/gateway',
      ],
    },
    {
      type: 'category',
      label: 'CLI',
      items: ['cli/reference'],
    },
    {
      type: 'category',
      label: 'Examples',
      items: ['examples/overview'],
    },
  ],
};

export default sidebars;
