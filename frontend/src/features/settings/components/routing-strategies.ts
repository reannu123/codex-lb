import type { DashboardSettings } from "@/features/settings/schemas";

export const STRATEGY_GUIDE_VALUES = {
  capacityWeighted: "capacity_weighted",
  relativeAvailability: "relative_availability",
  usageWeighted: "usage_weighted",
  roundRobin: "round_robin",
  fillFirst: "fill_first",
  sequentialDrain: "sequential_drain",
  resetDrain: "reset_drain",
  singleAccount: "single_account",
} as const satisfies Record<string, DashboardSettings["routingStrategy"]>;
