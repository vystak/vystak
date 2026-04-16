import clsx from 'clsx';
import Heading from '@theme/Heading';
import styles from './styles.module.css';

const FeatureList = [
  {
    title: 'Multi-Cloud',
    description: (
      <>
        Deploy to Docker, Azure Container Apps, or any platform from a single
        agent definition. Switch targets without changing the agent.
      </>
    ),
  },
  {
    title: 'OpenAI-Compatible API',
    description: (
      <>
        Every agent exposes <code>/v1/chat/completions</code> and{' '}
        <code>/v1/responses</code> out of the box. Drop-in replacement for any
        OpenAI client.
      </>
    ),
  },
  {
    title: 'Agent Collaboration',
    description: (
      <>
        Built-in A2A protocol, gateway routing, and multi-agent orchestration.
        Agents can discover and call each other natively.
      </>
    ),
  },
];

function Feature({title, description}) {
  return (
    <div className={clsx('col col--4')}>
      <div className="text--center padding-horiz--md">
        <Heading as="h3">{title}</Heading>
        <p>{description}</p>
      </div>
    </div>
  );
}

export default function HomepageFeatures() {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className="row">
          {FeatureList.map((props, idx) => (
            <Feature key={idx} {...props} />
          ))}
        </div>
      </div>
    </section>
  );
}
