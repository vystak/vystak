'use client';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main style={{ display: 'grid', placeItems: 'center', minHeight: '100vh' }}>
      <div style={{ maxWidth: 480, textAlign: 'center' }}>
        <h1 style={{ fontSize: 20 }}>Something went wrong</h1>
        <p>
          The control panel could not complete that request. The panel API may
          be unavailable.
        </p>
        <button type="button" onClick={() => reset()}>
          Try again
        </button>
      </div>
    </main>
  );
}
