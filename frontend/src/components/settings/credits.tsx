import { useRef } from "react";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/src/components/ui/accordion";

const dependencyGroups = [
  {
    name: "Backend",
    dependencies: [
      {
        name: "Bumble",
        licenseSlug: "bumble",
        license: "Apache-2.0",
        url: "https://github.com/google/bumble",
        description: "Bluetooth stack and controller communication",
      },
      {
        name: "pygame-ce",
        licenseSlug: "pygame-ce",
        license: "LGPL-2.1-or-later",
        url: "https://pyga.me/",
        description: "Controller input and multimedia support",
      },
      {
        name: "pywebview",
        licenseSlug: "pywebview",
        license: "BSD-3-Clause",
        url: "https://pywebview.flowrl.com/",
        description: "Desktop application window",
      },
      {
        name: "Starlette",
        licenseSlug: "starlette",
        license: "BSD-3-Clause",
        url: "https://www.starlette.io/",
        description: "Backend web framework",
      },
      {
        name: "Uvicorn",
        licenseSlug: "uvicorn",
        license: "BSD-3-Clause",
        url: "https://www.uvicorn.org/",
        description: "ASGI server",
      },
      {
        name: "websockets",
        licenseSlug: "websockets",
        license: "BSD-3-Clause",
        url: "https://websockets.readthedocs.io/",
        description: "WebSocket communication",
      },
    ],
  },
  {
    name: "Frontend",
    dependencies: [
      {
        name: "React",
        licenseSlug: "react",
        license: "MIT",
        url: "https://react.dev/",
        description: "User interface",
      },
      {
        name: "react-colorful",
        licenseSlug: "react-colorful",
        license: "MIT",
        url: "https://github.com/omgovich/react-colorful",
        description: "Controller colour pickers",
      },
      {
        name: "Vite",
        licenseSlug: "vite",
        license: "MIT",
        url: "https://vite.dev/",
        description: "Frontend development and builds",
      },
      {
        name: "TypeScript",
        licenseSlug: "typescript",
        license: "Apache-2.0",
        url: "https://www.typescriptlang.org/",
        description: "Static type checking",
      },
      {
        name: "TanStack Router",
        licenseSlug: "tanstack-router",
        license: "MIT",
        url: "https://tanstack.com/",
        description: "Routing",
      },
      {
        name: "TanStack Store",
        licenseSlug: "tanstack-store",
        license: "MIT",
        url: "https://tanstack.com/",
        description: "Application state",
      },
      {
        name: "Tailwind CSS",
        licenseSlug: "tailwindcss",
        license: "MIT",
        url: "https://tailwindcss.com/",
        description: "Styling",
      },
      {
        name: "Base UI",
        licenseSlug: "base-ui",
        license: "MIT",
        url: "https://base-ui.com/",
        description: "Accessible UI components",
      },
      {
        name: "shadcn/ui",
        licenseSlug: "shadcn-ui",
        license: "MIT",
        url: "https://ui.shadcn.com/",
        description: "UI component patterns and styling",
      },
      {
        name: "Blockly",
        licenseSlug: "blockly",
        license: "Apache-2.0",
        url: "https://developers.google.com/blockly",
        description: "Visual macro editor",
      },
      {
        name: "Video.js",
        licenseSlug: "videojs",
        license: "Apache-2.0",
        url: "https://videojs.com/",
        description: "Video playback",
      },
      {
        name: "Effect",
        licenseSlug: "effect",
        license: "MIT",
        url: "https://effect.website/",
        description: "Application logic and error handling",
      },
      {
        name: "Pierre Diffs",
        licenseSlug: "pierre-diffs",
        license: "Apache-2.0",
        url: "https://diffs.com/",
        description: "Code diff rendering",
      },
    ],
  },
  {
    name: "Design",
    dependencies: [
      {
        name: "Scoutie Sans",
        licenseSlug: "scoutie-sans",
        license: "OFL-1.1",
        url: "https://github.com/sursly/scoutie",
        description: "Interface font by the Scoutie Sans Project Authors",
      },
      {
        name: "Intel One Mono",
        licenseSlug: "intel-one-mono",
        license: "OFL-1.1",
        url: "https://github.com/intel/intel-one-mono",
        description: "Programming font by Intel",
      },
      {
        name: "Phosphor Icons",
        licenseSlug: "phosphor-icons",
        license: "MIT",
        url: "https://phosphoricons.com/",
        description: "Interface icons",
      },
      {
        name: "Input Prompts",
        licenseSlug: "kenney",
        license: "CC0",
        url: "https://kenney.nl/assets/input-prompts",
        description: "Controller icons by Kenney",
      },
    ],
  },
];

export default function Credits({ onToggleDebug }: { onToggleDebug?: () => void }) {
  const presses = useRef(0);
  return (
    <div className="space-y-4">
      <p>
        <span
          onClick={() => {
            presses.current += 1;
            if (presses.current === 10) {
              presses.current = 0;
              onToggleDebug?.();
            }
          }}
        >
          Ounce-bt
        </span>{" "}
        was developed by{" "}
        <a
          className="text-blue-500"
          target="_blank"
          rel="noopener noreferrer"
          href="https://github.com/jchu634"
        >
          JCHU634
        </a>
      </p>
      <p>
        We would like to thank Brikwerk for their{" "}
        <a
          className="text-blue-500"
          target="_blank"
          rel="noopener noreferrer"
          href="https://github.com/Brikwerk/nxbt"
        >
          NXBT project
        </a>{" "}
        <a
          className="text-blue-500"
          target="_blank"
          rel="noopener noreferrer"
          href="/licenses/nxbt"
        >
          (License)
        </a>
        <br />
        Ounce-bt's bluetooth core was implemented using NXBT's documentation, and uses/adapts some
        code from that project. <br />
        We would also like to thank typenoob for their work on their{" "}
        <a
          className="text-blue-500"
          target="_blank"
          rel="noopener noreferrer"
          href="https://github.com/typenoob/nxbt"
        >
          NXBT fork
        </a>{" "}
        as their bumble implementation was used to help understand the pairing protocol and fix the
        last bugs that prevented Ounce-bt's bumble implementation from working. <br />
        This could also not have been done without{" "}
        <a
          className="text-blue-500"
          target="_blank"
          rel="noopener noreferrer"
          href="https://github.com/dekuNukem/Nintendo_Switch_Reverse_Engineering"
        >
          dekuNukem's notes
        </a>{" "}
        which was used for implementing Rumble and Colours.
      </p>
      <p>
        Finally, we would like to thank the various open source library maintainers whose projects
        this is built upon.
      </p>
      <Accordion multiple>
        {dependencyGroups.map((group) => (
          <AccordionItem key={group.name} value={group.name}>
            <AccordionTrigger>{group.name} dependencies</AccordionTrigger>
            <AccordionContent>
              <ul className="space-y-2">
                {group.dependencies.map((dependency) => (
                  <li key={dependency.name}>
                    <a
                      className="text-blue-500"
                      href={dependency.url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {dependency.name}
                    </a>
                    <span className="text-muted-foreground"> · {dependency.description}</span>
                    <div className="text-xs text-muted-foreground">
                      License:{" "}
                      <a
                        target="_blank"
                        rel="noopener noreferrer"
                        href={`/licenses/${encodeURIComponent(dependency.licenseSlug)}`}
                      >
                        {dependency.license}
                      </a>
                    </div>
                  </li>
                ))}
              </ul>
            </AccordionContent>
          </AccordionItem>
        ))}
      </Accordion>
    </div>
  );
}
