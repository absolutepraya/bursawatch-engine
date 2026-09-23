import { SourceHub } from "@/components/source-hub";
import { parseSourceFilters } from "@/lib/source-filters";
export default async function DiscoverPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { platform, type } = parseSourceFilters(await searchParams);
  return <SourceHub key={`${platform}:${type}`} initialPlatform={platform} initialType={type} />;
}
