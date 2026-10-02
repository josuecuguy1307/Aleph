import { isOpenworkGatewayRuntime } from "./gateway-runtime";

export function canCreateWorkspaces() {
  return !isOpenworkGatewayRuntime();
}
