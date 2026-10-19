const licenses = import.meta.glob<string>("../licenses/*.md", {
  query: "?raw",
  import: "default",
  eager: true,
});

export function getLicenseText(slug: string): string | undefined {
  const path = `../licenses/${slug}.md`;
  return Object.hasOwn(licenses, path) ? licenses[path] : undefined;
}
