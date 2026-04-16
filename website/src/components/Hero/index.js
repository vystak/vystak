import clsx from 'clsx';
import Link from '@docusaurus/Link';
import CodeBlock from '@theme/CodeBlock';
import styles from './styles.module.css';

const HERO_YAML = `name: hello-bot
instructions: You are a friendly assistant.
model:
  name: claude
  provider: { name: anthropic, type: anthropic }
  model_name: claude-sonnet-4-20250514
platform:
  name: docker
  type: docker
  provider: { name: docker, type: docker }
channels:
  - name: api
    type: api
secrets:
  - name: ANTHROPIC_API_KEY
`;

export default function Hero() {
  return (
    <header className={styles.hero}>
      <div className="container">
        <div className={styles.grid}>
          <div className={styles.copy}>
            <h1 className={styles.title}>Vystak</h1>
            <p className={styles.tagline}>Declarative AI agent orchestration</p>
            <p className={styles.description}>
              Define your agent once. Deploy to Docker, Azure Container Apps, or
              any platform — from a single command.
            </p>
            <div className={styles.actions}>
              <Link
                className={clsx('button button--primary button--lg', styles.cta)}
                to="/docs/getting-started/intro">
                Get Started →
              </Link>
              <Link
                className={clsx('button button--secondary button--lg', styles.ghost)}
                to="https://github.com/vystak/AgentsStack">
                View on GitHub
              </Link>
            </div>
          </div>
          <div className={styles.codePane}>
            <div className={styles.codeWindow}>
              <div className={styles.codeWindowHeader}>
                <span className={styles.dot} style={{background: '#ef4444'}}></span>
                <span className={styles.dot} style={{background: '#f59e0b'}}></span>
                <span className={styles.dot} style={{background: '#10b981'}}></span>
                <span className={styles.codeWindowTitle}>vystak.yaml</span>
              </div>
              <CodeBlock language="yaml" className={styles.codeBlock}>
                {HERO_YAML}
              </CodeBlock>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
