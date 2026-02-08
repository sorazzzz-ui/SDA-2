import os
import uuid
from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user

app = Flask(__name__)

# Config
app.secret_key = 'super_secret_key'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov', 'avi', 'webm', 'mkv'}

# --- [ตาราง 1] เก็บการติดตาม (Followers) ---
followers = db.Table('followers',
    db.Column('follower_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('followed_id', db.Integer, db.ForeignKey('user.id'))
)

# --- [ตาราง 2] ระบบแจ้งเตือน (Notification) ---
class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id')) # แจ้งเตือนของใคร
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id')) # ใครเป็นคนทำ (เช่น คนที่มาฟอล)
    message = db.Column(db.String(255), nullable=False) # ข้อความ
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)

    sender = db.relationship('User', foreign_keys=[sender_id])

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    
    # ความสัมพันธ์ Follow (Self-Referencing Many-to-Many)
    followed = db.relationship(
        'User', secondary=followers,
        primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        backref=db.backref('followers', lazy='dynamic'), lazy='dynamic'
    )

    # แจ้งเตือนของฉัน
    notifications = db.relationship('Notification', foreign_keys=[Notification.user_id], backref='user', lazy='dynamic')

    # เช็คว่าติดตามหรือยัง?
    def is_following(self, user):
        return self.followed.filter(followers.c.followed_id == user.id).count() > 0

    # สั่งติดตาม (Follow)
    def follow(self, user):
        if not self.is_following(user):
            self.followed.append(user)
            # สร้างแจ้งเตือนไปบอกเขา
            notif = Notification(user_id=user.id, sender_id=self.id, message="เริ่มติดตามคุณ")
            db.session.add(notif)

    # เลิกติดตาม (Unfollow)
    def unfollow(self, user):
        if self.is_following(user):
            self.followed.remove(user)

    # ฟังก์ชันช่วยสำหรับหน้า HTML
    def is_following_by_name(self, target_username):
        target = User.query.filter_by(username=target_username).first()
        if not target: return False
        return self.is_following(target)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    author = db.Column(db.String(100), nullable=False)
    media_list = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.String(50), nullable=False)

with app.app_context():
    db.create_all()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Routes ---

@app.route('/')
def home():
    posts = Post.query.order_by(Post.id.desc()).all()
    VIDEO_EXTS = {'mp4', 'mov', 'avi', 'webm', 'mkv'}

    for post in posts:
        post.struct_media = []
        if post.media_list:
            paths = post.media_list.split(',')
            for p in paths:
                p = p.strip()
                if not p: continue
                try:
                    ext = p.split('.')[-1].lower()
                except:
                    ext = ""
                m_type = 'video' if ext in VIDEO_EXTS else 'image'
                post.struct_media.append({'path': p, 'type': m_type})
    
    return render_template('index.html', posts=posts)

# --- [System] Follow Like IG ---

@app.route('/follow/<username>')
@login_required
def follow(username):
    user_to_follow = User.query.filter_by(username=username).first()
    if user_to_follow and user_to_follow != current_user:
        current_user.follow(user_to_follow)
        db.session.commit()
        flash(f'ติดตาม {username} แล้ว!')
    return redirect(request.referrer or url_for('home'))

@app.route('/unfollow/<username>')
@login_required
def unfollow(username):
    user_to_unfollow = User.query.filter_by(username=username).first()
    if user_to_unfollow:
        current_user.unfollow(user_to_unfollow)
        db.session.commit()
        flash(f'เลิกติดตาม {username} แล้ว')
    return redirect(request.referrer or url_for('home'))

@app.route('/following')
@login_required
def following_page():
    # ดูรายการคนที่เราติดตาม
    following_list = current_user.followed.all()
    return render_template('following.html', following_list=following_list)

@app.route('/notifications')
@login_required
def notifications():
    # 1. ดึงแจ้งเตือนทั้งหมดออกมา
    notifs = current_user.notifications.order_by(Notification.timestamp.desc()).all()
    
    # 2. [ส่วนที่เพิ่ม] วนลูปสั่งให้ทุกอันกลายเป็น "อ่านแล้ว" (is_read = True)
    for n in notifs:
        if not n.is_read:
            n.is_read = True
            
    # 3. บันทึกลง Database
    db.session.commit()
    
    return render_template('notifications.html', notifs=notifs)
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('ชื่อซ้ำครับ')
            return redirect(url_for('register'))
        hashed_pw = generate_password_hash(password, method='scrypt')
        new_user = User(username=username, password=hashed_pw)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('home'))
        else:
            flash('Login Failed')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route('/create', methods=['GET', 'POST'])
@login_required
def create_post():
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        author = current_user.username 
        
        media_paths = []
        if 'file' in request.files:
            files = request.files.getlist('file')
            for file in files:
                if file and allowed_file(file.filename):
                    ext = os.path.splitext(file.filename)[1].lower()
                    new_filename = f"{uuid.uuid4().hex}{ext}"
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], new_filename))
                    media_paths.append(f'uploads/{new_filename}')
        
        media_string = ",".join(media_paths)
        thai_time = (datetime.utcnow() + timedelta(hours=7)).strftime("%d/%m/%Y %H:%M")

        new_post = Post(title=title, content=content, author=author, media_list=media_string, timestamp=thai_time)
        db.session.add(new_post)
        db.session.commit()
        return redirect(url_for('home'))
    return render_template('create.html')

@app.route('/status')
def status_check():
    return redirect("https://check-status-final-88358153370.asia-southeast1.run.app")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)