
import os, json, uuid
from flask import Flask, render_template, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
import google.auth, google.generativeai as genai, pandas as pd


db = SQLAlchemy()
migrate = Migrate()


class User(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    messages = db.relationship('Message', backref='author', lazy='dynamic', cascade="all, delete-orphan")

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(36), db.ForeignKey('user.id'), nullable=False)
    role = db.Column(db.String(10), nullable=False)
    content = db.Column(db.Text, nullable=False)
    feedback = db.Column(db.Integer, default=0, nullable=False)


def load_professions_from_csv(filepath):
    try:
        df = pd.read_csv(filepath).fillna('')
        return df.to_dict('records')
    except Exception as e:
        print(f"CSV Yükleme Hatası: {e}"); return []

def search_engine_bot(conversation_history, professions_database):
    if not professions_database: return "[]"
    database_text = json.dumps(professions_database, indent=2, ensure_ascii=False)
    prompt = (f"Bir sohbet geçmişi ve meslek veritabanı analizi yap. Kullanıcının son isteğiyle en alakalı en fazla 5 mesleğin TÜM BİLGİLERİNİ, verilen JSON veritabanından bul ve yeni bir JSON listesi olarak döndür.\n\nSOHBET: {conversation_history}\n\nVERİTABANI: {database_text}\n\nAlakalı meslekleri JSON listesi olarak döndür. Bulamazsan boş bir liste `[]` döndür.")
    search_model = genai.GenerativeModel('gemini-1.5-flash-latest')
    try:
        response = search_model.generate_content(prompt)
        return response.text.strip().lstrip("```json").rstrip("```").strip()
    except Exception as e:
        print(f"Arama Botu Hatası: {e}"); return "[]"


def create_app():
    app = Flask(__name__)
    
    app.config.from_mapping(
        SECRET_KEY='bu-anahtari-degistir-lutfen',
        SQLALCHEMY_DATABASE_URI='sqlite:///' + os.path.join(os.path.abspath(os.path.dirname(__file__)), 'instance', 'app.db'),
        SQLALCHEMY_TRACK_MODIFICATIONS=False
    )
    
    db.init_app(app)
    migrate.init_app(app, db)
    
    
    admin = Admin(app, name='MeslekAtlası Yönetim', template_mode='bootstrap3')

    
    class MessageView(ModelView):
        column_list = ('id', 'author', 'role', 'content', 'feedback')
        column_searchable_list = ['content']
        column_filters = ['role', 'feedback']
        column_default_sort = ('id', True)
        can_create = False
        can_edit = True
        can_delete = True

    class UserView(ModelView):
        column_list = ['id']
        column_searchable_list = ['id']
        can_create = False

    
    admin.add_view(UserView(User, db.session, name='Kullanıcılar'))
    admin.add_view(MessageView(Message, db.session, name='Mesajlar'))
    
    
    try:
        api_key = "BURAYA_YENİ_API_ANAHTARINI_YAPIŞTIR"
        os.environ['GOOGLE_API_KEY'] = api_key
        genai.configure(api_key=api_key)
    except Exception as e: 
        print(f"API Hatası: {e}")

    with app.app_context():
        app.config['ALL_PROFESSIONS_DATA'] = load_professions_from_csv('meslek_veritabani_2025.csv')
        app.config['MAIN_CHAT_BOT'] = genai.GenerativeModel('gemini-1.5-flash-latest')

    @app.before_request
    def ensure_user_session():
        if 'user_id' not in session:
            with app.app_context():
                new_user = User(); db.session.add(new_user); db.session.commit(); session['user_id'] = new_user.id

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/get_history', methods=['POST'])
    def get_history():
        user = User.query.get(session.get('user_id'))
        if user:
            history = [{"id": msg.id, "role": msg.role, "content": msg.content, "feedback": msg.feedback} for msg in user.messages.order_by(Message.id.asc())]
            return jsonify(history)
        return jsonify([])

    @app.route('/chat', methods=['POST'])
    def chat():
        user = User.query.get(session.get('user_id'))
        if not user: return jsonify({'error': 'Kullanıcı bulunamadı'}), 404
        
        user_message_content = request.json['message']
        user_message_db = Message(user_id=user.id, role='user', content=user_message_content)
        db.session.add(user_message_db); db.session.commit()
        history_for_prompt = "".join([f"{'Kullanıcı' if msg.role == 'user' else 'Bot'}: {msg.content}\n" for msg in user.messages.order_by(Message.id.desc()).limit(8)])
        relevant_data_json_str = search_engine_bot(history_for_prompt, app.config['ALL_PROFESSIONS_DATA'])
        final_prompt = (f"Bir kariyer danışmanısın...") # Kısaltıldı
        response = app.config['MAIN_CHAT_BOT'].generate_content(final_prompt)
        bot_message_content = response.text
        bot_message_db = Message(user_id=user.id, role='model', content=bot_message_content)
        db.session.add(bot_message_db); db.session.commit()
        return jsonify({"id": bot_message_db.id, "reply": bot_message_content})

    @app.route('/feedback', methods=['POST'])
    def feedback():
        data = request.json
        message = Message.query.get(data.get('message_id'))
        if message and message.user_id == session.get('user_id'):
            message.feedback = int(data.get('feedback_value'))
            db.session.commit()
            return jsonify({'status': 'success'})
        return jsonify({'status': 'error'}), 404

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, port=5001)