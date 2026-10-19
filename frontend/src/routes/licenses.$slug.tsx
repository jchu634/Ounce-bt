import { createFileRoute, notFound } from "@tanstack/react-router";
import { getLicenseText } from "@/src/lib/licenses";

export const Route = createFileRoute("/licenses/$slug")({
  loader: ({ params }) => {
    const text = getLicenseText(params.slug);
    if (text === undefined) throw notFound();
    return text;
  },
  component: LicensePage,
  notFoundComponent: () => <p>License not found.</p>,
});

function LicensePage() {
  const text = Route.useLoaderData();

  return <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{text}</pre>;
}
