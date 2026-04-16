import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import Hero from '@site/src/components/Hero';
import CodeShowcase from '@site/src/components/CodeShowcase';

export default function Home() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <Layout
      title={`${siteConfig.title} — ${siteConfig.tagline}`}
      description="Declarative AI agent orchestration. Define once, deploy everywhere.">
      <Hero />
      <main>
        <CodeShowcase />
      </main>
    </Layout>
  );
}
