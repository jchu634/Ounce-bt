import type { SVGProps } from "react";

import { joyConRightPaths } from "./joycon-paths";

const SvgSwitchJoyconRight = (props: SVGProps<SVGSVGElement>) => (
  <svg xmlns="http://www.w3.org/2000/svg" width={64} height={64} viewBox="0 0 64 64" {...props}>
    <path
      fill="currentColor"
      fillRule="evenodd"
      d={joyConRightPaths.body + joyConRightPaths.buttons}
    />
  </svg>
);
export default SvgSwitchJoyconRight;
