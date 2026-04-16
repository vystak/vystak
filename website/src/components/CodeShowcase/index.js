import CodeBlock from '@theme/CodeBlock';
import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';
import styles from './styles.module.css';

const SHOWCASE_YAML = `name: hello-bot
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

const SHOWCASE_PYTHON = `import vystak

anthropic = vystak.Provider(name="anthropic", type="anthropic")
docker = vystak.Provider(name="docker", type="docker")

agent = vystak.Agent(
    name="hello-bot",
    instructions="You are a friendly assistant.",
    model=vystak.Model(
        name="claude",
        provider=anthropic,
        model_name="claude-sonnet-4-20250514",
    ),
    platform=vystak.Platform(name="docker", type="docker", provider=docker),
    channels=[vystak.Channel(name="api", type=vystak.ChannelType.API)],
    secrets=[vystak.Secret(name="ANTHROPIC_API_KEY")],
)
`;

export default function CodeShowcase() {
  return (
    <section className={styles.section}>
      <div className="container">
        <div className={styles.header}>
          <h2 className={styles.heading}>Define once. Deploy anywhere.</h2>
          <p className={styles.subhead}>The same agent, in YAML or Python.</p>
        </div>
        <div className={styles.tabs}>
          <Tabs groupId="agent-language">
            <TabItem value="yaml" label="YAML" default>
              <CodeBlock language="yaml">{SHOWCASE_YAML}</CodeBlock>
            </TabItem>
            <TabItem value="python" label="Python">
              <CodeBlock language="python">{SHOWCASE_PYTHON}</CodeBlock>
            </TabItem>
          </Tabs>
        </div>
      </div>
    </section>
  );
}
