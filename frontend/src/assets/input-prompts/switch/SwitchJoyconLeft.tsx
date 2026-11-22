import type { SVGProps } from "react";

import { joyConLeftPaths } from "./joycon-paths";

const SvgSwitchJoyconLeft = (props: SVGProps<SVGSVGElement>) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={64} height={64} viewBox="0 0 64 64" {...props}>
    <path
      fill="currentColor"
      fillRule="evenodd"
      d={joyConLeftPaths.body + joyConLeftPaths.buttons}
    />
  </svg>
);
export default SvgSwitchJoyconLeft;
