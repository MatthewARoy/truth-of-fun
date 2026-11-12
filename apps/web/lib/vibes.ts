/** Interest tags offered at sign-up and on the account page. */
export const VIBE_OPTIONS = [
  { tag: "#LiveMusic", label: "Live Music", emoji: "🎵" },
  { tag: "#Comedy", label: "Comedy", emoji: "😂" },
  { tag: "#Nightlife", label: "Nightlife & Clubs", emoji: "🌃" },
  { tag: "#FoodAndDrink", label: "Food & Drink", emoji: "🍷" },
  { tag: "#Outdoors", label: "Outdoors & Nature", emoji: "🌲" },
  { tag: "#intellectual", label: "Tech & Startups", emoji: "💻" },
  { tag: "#Art", label: "Art & Museums", emoji: "🎨" },
  { tag: "#Sports", label: "Sports", emoji: "⚽" },
  { tag: "#theatre", label: "Theater & Film", emoji: "🎭" },
  { tag: "#Wellness", label: "Wellness & Fitness", emoji: "🧘" },
  { tag: "#familyfriendly", label: "Family Friendly", emoji: "👨‍👩‍👧" },
  { tag: "#Free", label: "Free Events", emoji: "🆓" },
  { tag: "#Social", label: "Mixers & Networking", emoji: "🤝" },
  { tag: "#HighEnergy", label: "Raves & Festivals", emoji: "🔥" },
  { tag: "#Chill", label: "Chill & Relaxed", emoji: "☕" },
  { tag: "#workshop", label: "Talks & Workshops", emoji: "📚" },
] as const;

export function vibeLabel(tag: string): string {
  return VIBE_OPTIONS.find((option) => option.tag === tag)?.label ?? tag;
}
