# MobileCybench GCP Setup Guide
## Prerequisites

1. **Google Cloud Account**: You need a Google account with GCP access
2. **GCP Project**: Create a new GCP project or use an existing one
3. **Billing**: Enable billing on your GCP project
4. **gcloud CLI**: Install the gcloud command-line tool

## Authenticate and Setup

```bash
gcloud auth login

gcloud config set project YOUR-PROJECT-ID # can be found on the gcp console

gcloud config set compute/zone us-west1-b
```

## Creating VM instance
Run this command to create a VM from the MobileCybench template:
```bash
gcloud compute instances create my-mobilecybench-vm \
  --image=mobilecybench-v1 \        # the user needs access to this image
  --image-project=mobilecybench \
  --machine-type=n2-standard-4 \
  --boot-disk-size=100GB \          # disk size can be increased, but not decreased
  --boot-disk-type=pd-balanced \
  --enable-nested-virtualization \
  --zone=us-west1-b
```

> For giving access to users:
```bash
  gcloud compute images add-iam-policy-binding mobilecybench-v1 \
    --member='user:person1@gmail.com' \
    --role='roles/compute.imageUser'
```

## Setting up Workspace

1. Clone MobileCybench Repo
2. Set up Python virtual environment (not perfect yet, install dependencies as needed)
3. `docker compose -f orchestrator/docker-compose.yml up -d`. The VM should have the built images, but you can prune and rebuild as well. 
4. `docker compose -it mobilecybench-orchestrator bash`
   * may need more dependencies depending on the app (currently not perfect yet - can build some apps, but haven't tested for all apps)
   * for audiobookshelf, needs java 21. `export PATH=$JAVA_HOME/bin:$PATH` before `./setup_app_source.sh`
