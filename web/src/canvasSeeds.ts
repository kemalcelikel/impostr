// Display-only fixtures. Content, logical trees and initial coordinates are
// deliberately separate; none of these describe the project's Markdown/tasks.
export type SampleCardContent = {
  id: string;
  title: string;
  body: string;
  footer: string;
};

const cardTitles = [
  ["ideas-root", "Lorem ipsum · Ideas"],
  ["ideas-research", "Dolor sit amet · Research"],
  ["ideas-shape", "Consectetur · Shape"],
  ["ideas-sketch", "Adipiscing elit · Sketch"],
  ["ideas-prototype", "Sed do eiusmod · Prototype"],
  ["journey-root", "Lorem ipsum · Journey"],
  ["journey-arrive", "Ut enim · Arrive"],
  ["journey-explore", "Ad minim veniam · Explore"],
  ["journey-return", "Quis nostrud · Return"],
  ["release-root", "Lorem ipsum · Release"],
  ["release-prepare", "Duis aute · Prepare"],
  ["release-check", "Irure dolor · Check"],
  ["release-share", "In reprehenderit · Share"],
] as const;

export const sampleCards: Record<string, SampleCardContent> = Object.fromEntries(
  cardTitles.map(([id, title], index) => [
    id,
    {
      id,
      title,
      body:
        index % 2 === 0
          ? "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua."
          : "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit.",
      footer: `Sample metadata only · ${index % 2 === 0 ? "Amber" : "Fern"} lane · ${index + 3} points · Lorem ipsum`,
    },
  ]),
);

export const sampleBoards = [
  {
    id: "ideas",
    title: "Idea tree",
    cardIds: ["ideas-root", "ideas-research", "ideas-shape", "ideas-sketch", "ideas-prototype"],
  },
  {
    id: "journey",
    title: "Journey tree",
    cardIds: ["journey-root", "journey-arrive", "journey-explore", "journey-return"],
  },
  {
    id: "release",
    title: "Release tree",
    cardIds: ["release-root", "release-prepare", "release-check", "release-share"],
  },
];

export type SampleRelation = { parent: string; child: string };
export const sampleHierarchy: Record<string, SampleRelation[]> = {
  ideas: [
    { parent: "ideas-root", child: "ideas-research" },
    { parent: "ideas-root", child: "ideas-shape" },
    { parent: "ideas-shape", child: "ideas-sketch" },
    { parent: "ideas-shape", child: "ideas-prototype" },
  ],
  journey: [
    { parent: "journey-root", child: "journey-arrive" },
    { parent: "journey-arrive", child: "journey-explore" },
    { parent: "journey-explore", child: "journey-return" },
  ],
  release: [
    { parent: "release-root", child: "release-prepare" },
    { parent: "release-root", child: "release-check" },
    { parent: "release-check", child: "release-share" },
  ],
};

export const sampleLayouts: Record<
  string,
  {
    positions: Record<string, { x: number; y: number }>;
    viewport: { x: number; y: number; zoom: number };
  }
> = {
  ideas: {
    positions: {
      "ideas-root": { x: 0, y: 150 },
      "ideas-research": { x: 380, y: 0 },
      "ideas-shape": { x: 380, y: 300 },
      "ideas-sketch": { x: 760, y: 150 },
      "ideas-prototype": { x: 760, y: 450 },
    },
    viewport: { x: 40, y: 45, zoom: 0.7 },
  },
  journey: {
    positions: {
      "journey-root": { x: 0, y: 0 },
      "journey-arrive": { x: 380, y: 100 },
      "journey-explore": { x: 760, y: 200 },
      "journey-return": { x: 1140, y: 300 },
    },
    viewport: { x: 40, y: 60, zoom: 0.6 },
  },
  release: {
    positions: {
      "release-root": { x: 0, y: 150 },
      "release-prepare": { x: 380, y: 0 },
      "release-check": { x: 380, y: 300 },
      "release-share": { x: 760, y: 300 },
    },
    viewport: { x: 40, y: 45, zoom: 0.7 },
  },
};
