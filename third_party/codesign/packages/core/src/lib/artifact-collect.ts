import { type Artifact, DEFAULT_SOURCE_ENTRY } from '@open-codesign/shared';

export interface Collected {
  text: string;
  artifacts: Artifact[];
}

export function createDesignSourceArtifact(
  content: string,
  index: number,
  entryPath: string = DEFAULT_SOURCE_ENTRY,
): Artifact {
  return {
    id: `design-${index + 1}`,
    type: 'html',
    title: 'Design',
    content,
    designParams: [],
    sourceFormat: 'jsx',
    renderRuntime: 'react',
    entryPath,
    createdAt: new Date().toISOString(),
  };
}

export function createHtmlArtifact(content: string, index: number): Artifact {
  return createDesignSourceArtifact(content, index);
}

export function stripEmptyFences(text: string): string {
  // Streaming parsers emit ```html and the closing ``` as text deltas around
  // structured artifact events, so the artifact body is consumed but the empty
  // fence shell remains in the chat message. Drop those leftover wrappers.
  return text.replace(/```[a-zA-Z0-9]*\s*```/g, '').trim();
}
