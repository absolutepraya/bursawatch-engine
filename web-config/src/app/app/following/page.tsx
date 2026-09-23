import { SourceHub } from "@/components/source-hub";
import { parseSourceFilters } from "@/lib/source-filters";
export default async function FollowingPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { platform, type } = parseSourceFilters(await searchParams);
  return (
    <SourceHub
      key={`${platform}:${type}`}
      following
      initialPlatform={platform}
      initialType={type}
    />
  );
}
