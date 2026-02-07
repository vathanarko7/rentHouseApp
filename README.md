## Next deployment to VM Google Cloud
cd /opt/rentHouseApp

git pull

## if requirements.txt changed:

source .venv/bin/activate

pip install -r requirements.txt

python manage.py migrate

python manage.py collectstatic --noinput

sudo systemctl restart renthouse

sudo systemctl restart nginx
