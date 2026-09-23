export const brokers = [
  {
    id: "bri-danareksa",
    name: "BRI Danareksa Sekuritas",
    shortName: "BRI Danareksa",
    logo: "/brokers/brids-logo.png",
    portrait: "/brokers/brids-leader.jpg",
    building: "/brokers/brids-building.jpg",
    leader: "Fifi Virgantria",
    role: "Acting president director",
    office: "BRI II Building",
    location: "Sudirman, Jakarta",
    description:
      "Equity research, company updates and market commentary from the BRI group’s securities firm.",
    coverage: ["Equity research", "Market commentary"],
    website: "https://www.bridanareksasekuritas.co.id/",
    profile:
      "https://www.bridanareksasekuritas.co.id/dukung-trading-di-tengah-volatilitas-dengan-auto-order-brids-raih-penghargaan-icaii-2026",
  },
  {
    id: "phintraco",
    name: "Phintraco Sekuritas",
    shortName: "Phintraco",
    logo: "/brokers/phintraco-logo.svg",
    portrait: "/brokers/phintraco-leader.png",
    building: "/brokers/phintraco-east.jpg",
    leader: "Ferawati",
    role: "President director",
    office: "The East Tower",
    location: "Mega Kuningan, Jakarta",
    description:
      "Daily and technical research, weekly market notes and company updates for Indonesian equities.",
    coverage: ["Technical research", "Company updates"],
    website: "https://phintracosekuritas.com/",
    profile: "https://phintracosekuritas.com/tentang-kami/",
  },
] as const;

export type Broker = (typeof brokers)[number];
export type BrokerId = Broker["id"];
export const findBroker = (id: string) => brokers.find((broker) => broker.id === id);
