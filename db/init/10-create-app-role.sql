\getenv app_db_user IMPOSTR_APP_DB_USER
\getenv app_db_password IMPOSTR_APP_DB_PASSWORD
\getenv app_db_name POSTGRES_DB

CREATE ROLE :"app_db_user" LOGIN PASSWORD :'app_db_password';
GRANT CONNECT ON DATABASE :"app_db_name" TO :"app_db_user";
GRANT USAGE, CREATE ON SCHEMA public TO :"app_db_user";
