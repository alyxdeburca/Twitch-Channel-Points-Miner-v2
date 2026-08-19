# Twitch endpoints
URL = "https://www.twitch.tv"
IRC = "irc.chat.twitch.tv"
IRC_PORT = 6667
WEBSOCKET = "wss://pubsub-edge.twitch.tv/v1"
CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
DROP_ID = "c2542d6d-cd10-4532-919b-3d19f30a768b"

USER_AGENTS = {
    "Windows": {
        "CHROME": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "FIREFOX": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    },
    "Linux": {
        "CHROME": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "FIREFOX": "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
    },
}

BRANCH = "master"
GITHUB_url = (
    "https://raw.githubusercontent.com/Tkd-Alex/Twitch-Channel-Points-Miner-v2/"
    + BRANCH
)


class GQLOperations:
    url = "https://gql.twitch.tv/gql"
    # IMPORTANT: These operations are sent with the full GraphQL query text,
    # NOT with persisted-query sha256Hash values. Twitch periodically rotates
    # the hashes used by the web client, which made the old persisted-query
    # approach fail with "PersistedQueryNotFound" for everyone. The gql
    # endpoint still accepts plain query text (verified live), and query text
    # does not rot the way hashes do. Each query below was validated against
    # the live schema on 2026-08-19. Queries that return "failed integrity
    # check" / "unauthenticated" without valid credentials are schema-valid;
    # those errors are Twitch's semantic/auth rejection of fabricated IDs.
    WithIsStreamLiveQuery = {
        "operationName": "WithIsStreamLiveQuery",
        "query": "query WithIsStreamLiveQuery($id: ID!){user(id:$id){id stream{id}}}",
    }
    VideoPlayerStreamInfoOverlayChannel = {
        "operationName": "VideoPlayerStreamInfoOverlayChannel",
        "query": "query VideoPlayerStreamInfoOverlayChannel($channel: String!){user(login:$channel){stream{id tags{id} viewersCount} broadcastSettings{title game{id displayName}}}}",
    }
    ClaimCommunityPoints = {
        "operationName": "ClaimCommunityPoints",
        "query": "mutation ClaimCommunityPoints($input: ClaimCommunityPointsInput!){claimCommunityPoints(input:$input){error{code}}}",
    }
    DropsPage_ClaimDropRewards = {
        "operationName": "DropsPage_ClaimDropRewards",
        "query": "mutation DropsPage_ClaimDropRewards($input: ClaimDropRewardsInput!){claimDropRewards(input:$input){status}}",
    }
    ChannelPointsContext = {
        "operationName": "ChannelPointsContext",
        "query": "query ChannelPointsContext($channelLogin: String!){community: user(login:$channelLogin){id channel{self{communityPoints{balance availableClaim{id} activeMultipliers{factor}}}}}}",
    }
    JoinRaid = {
        "operationName": "JoinRaid",
        "query": "mutation JoinRaid($input: JoinRaidInput!){joinRaid(input:$input){__typename}}",
    }
    ModViewChannelQuery = {
        "operationName": "ModViewChannelQuery",
        "query": "query ModViewChannelQuery($channelLogin: String!){user(login:$channelLogin){id self{isModerator}}}",
    }
    Inventory = {
        "operationName": "Inventory",
        "variables": {},
        "query": "query Inventory{currentUser{inventory{dropCampaignsInProgress{id timeBasedDrops{id self{hasPreconditionsMet currentMinutesWatched dropInstanceID isClaimed}}}}}}",
    }
    MakePrediction = {
        "operationName": "MakePrediction",
        "query": "mutation MakePrediction($input: MakePredictionInput!){makePrediction(input:$input){error{code}}}",
    }
    ViewerDropsDashboard = {
        "operationName": "ViewerDropsDashboard",
        "variables": {},
        "query": "query ViewerDropsDashboard{currentUser{dropCampaigns{id status}}}",
    }
    DropCampaignDetails = {
        "operationName": "DropCampaignDetails",
        "query": "query DropCampaignDetails($dropID: ID!, $channelLogin: ID!){user(id:$channelLogin){dropCampaign(id:$dropID){id name status game{id displayName} allow{channels{id}} startAt endAt timeBasedDrops{id name benefitEdges{benefit{name}} requiredMinutesWatched startAt endAt}}}}",
    }
    DropsHighlightService_AvailableDrops = {
        "operationName": "DropsHighlightService_AvailableDrops",
        "query": "query DropsHighlightService_AvailableDrops($channelID: ID!){channel(id:$channelID){viewerDropCampaigns{id}}}",
    }
    ReportMenuItem = {  # Use for replace https://api.twitch.tv/helix/users?login={self.username}
        "operationName": "ReportMenuItem",
        "query": "query ReportMenuItem($channelLogin: String!){user(login:$channelLogin){id}}",
    }
    ChannelFollows = {
        "operationName": "ChannelFollows",
        "variables": {"limit": 100, "order": "ASC"},
        "query": "query ChannelFollows($limit: Int!, $order: SortOrder, $cursor: Cursor){user{id follows(first:$limit, order:$order, after:$cursor){edges{cursor node{login}} pageInfo{hasNextPage}}}}",
    }
