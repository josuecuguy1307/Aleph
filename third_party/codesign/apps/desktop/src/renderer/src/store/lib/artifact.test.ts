import { describe, expect, it } from 'vitest';
import { looksRunnableArtifact } from './artifact';

describe('looksRunnableArtifact', () => {
  it('accepts runnable JSX with CSS functions inside template literals', () => {
    const source = `const styles = \`
.card {
  color: oklch(30% 0.03 160);
  transition: transform 180ms cubic-bezier(0.16, 1, 0.3, 1);
}
\`;
function App() {
  return <main><style>{styles}</style><section className="card">Ready</section></main>;
}
ReactDOM.createRoot(document.getElementById('root')).render(<App />);`;

    expect(looksRunnableArtifact(source)).toBe(true);
  });

  it('rejects JSX that is missing the React mount call', () => {
    expect(looksRunnableArtifact('function App() { return <main />; }')).toBe(false);
  });

  it('rejects clearly truncated JSX outside strings', () => {
    const source = `function App() {
  const broken = { a: { b: { c: { d: 1 };
  return <main>Bad</main>;
}
ReactDOM.createRoot(document.getElementById('root')).render(<App />);`;

    expect(looksRunnableArtifact(source)).toBe(false);
  });
});
