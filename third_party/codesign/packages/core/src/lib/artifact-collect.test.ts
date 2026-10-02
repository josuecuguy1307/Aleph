import { describe, expect, it } from 'vitest';
import { createDesignSourceArtifact, createHtmlArtifact } from './artifact-collect';

describe('artifact collection', () => {
  it('marks generated workspace content as JSX design source metadata', () => {
    const artifact = createDesignSourceArtifact('function App() { return <main />; }', 0);

    expect(artifact.type).toBe('html');
    expect(artifact.sourceFormat).toBe('jsx');
    expect(artifact.renderRuntime).toBe('react');
    expect(artifact.entryPath).toBe('App.jsx');
  });

  it('keeps createHtmlArtifact as a compatibility wrapper', () => {
    const artifact = createHtmlArtifact('function App() { return <main />; }', 0);

    expect(artifact.sourceFormat).toBe('jsx');
    expect(artifact.renderRuntime).toBe('react');
    expect(artifact.entryPath).toBe('App.jsx');
  });
});
