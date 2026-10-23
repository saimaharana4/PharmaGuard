# Exchange the existing GitLab OIDC identity in memory. The scanner image already has Ruby.
# No gcloud installation, service-account key, token file or long-lived registry password.
require 'json'
require 'net/http'
require 'uri'

def post_json(url, body, bearer = nil, form: false)
  uri = URI(url)
  request = Net::HTTP::Post.new(uri)
  request['Authorization'] = "Bearer #{bearer}" if bearer
  if form
    request.set_form_data(body)
  else
    request['Content-Type'] = 'application/json'
    request.body = JSON.generate(body)
  end
  response = Net::HTTP.start(uri.hostname, uri.port, use_ssl: true,
                            open_timeout: 20, read_timeout: 45) { |http| http.request(request) }
  abort "Registry authentication failed (HTTP #{response.code})" unless response.is_a?(Net::HTTPSuccess)
  JSON.parse(response.body)
end

provider = ENV.fetch('GCP_WIF_PROVIDER')
account = ENV.fetch('GCP_DEPLOY_SERVICE_ACCOUNT')
abort 'Invalid identity provider' unless provider.match?(%r{\Aprojects/\d+/locations/global/workloadIdentityPools/[\w-]+/providers/[\w-]+\z})
abort 'Invalid service account' unless account.match?(/\A[a-z0-9-]+@[a-z0-9-]+\.iam\.gserviceaccount\.com\z/)
component = ENV.fetch('COMPONENT')
abort 'Unexpected image component' unless %w[api web edge].include?(component)
image = ENV.fetch("#{component.upcase}_IMAGE")
abort 'An immutable Artifact Registry digest is required' unless image.match?(%r{\Aasia-south1-docker\.pkg\.dev/[a-z0-9/_-]+@sha256:[a-f0-9]{64}\z})

federated = post_json('https://sts.googleapis.com/v1/token', {
  'audience' => "//iam.googleapis.com/#{provider}",
  'grant_type' => 'urn:ietf:params:oauth:grant-type:token-exchange',
  'requested_token_type' => 'urn:ietf:params:oauth:token-type:access_token',
  'scope' => 'https://www.googleapis.com/auth/cloud-platform',
  'subject_token_type' => 'urn:ietf:params:oauth:token-type:jwt',
  'subject_token' => ENV.fetch('GCP_ID_TOKEN')
}, form: true).fetch('access_token')
access = post_json("https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/#{account}:generateAccessToken",
                   { 'scope' => ['https://www.googleapis.com/auth/cloud-platform'], 'lifetime' => '3600s' },
                   federated).fetch('accessToken')
ENV.delete('GCP_ID_TOKEN')
ENV['CS_IMAGE'] = image
ENV['CS_REGISTRY_USER'] = 'oauth2accesstoken'
ENV['CS_REGISTRY_PASSWORD'] = access
exec('gtcs', 'scan')
