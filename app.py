
"""
BookMyShow – Simple Backend
Cache  : In-process memory (SimpleCache)
Session: Filesystem
DB     : SQLite
"""

from flask import Flask, request, jsonify, session, render_template, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_caching import Cache
from flask_session import Session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime, timedelta
import uuid
import random
import logging

app = Flask(__name__)
CORS(app, supports_credentials=True)

app.config.update(
    SECRET_KEY="dev-secret",

    SQLALCHEMY_DATABASE_URI="sqlite:///bookmyshow.db",
    SQLALCHEMY_TRACK_MODIFICATIONS=False,

    SESSION_TYPE="filesystem",
    SESSION_PERMANENT=False,
    SESSION_USE_SIGNER=True,

    CACHE_TYPE="SimpleCache",
    CACHE_DEFAULT_TIMEOUT=300,
)


db = SQLAlchemy(app)
cache = Cache(app)
Session(app)

@app.route('/')
def home():
    if not session.get('user_id'):
        return redirect('/login')
    return render_template('home.html')

@app.route('/events', methods=['GET', 'POST'])
def events_page():
    if request.method == 'POST':
        location = request.form.get('location')
        events = get_events_by_location(location)
        return render_template('events.html', events=events, location=location)
    location = request.args.get('location')
    if not location:
        locations = [loc[0] for loc in db.session.query(Theater.city).distinct().all()]
        return render_template('select_location.html', locations=locations)
    events = get_events_by_location(location)
    return render_template('events.html', events=events, location=location)

@app.route('/select-location', methods=['GET', 'POST'])
def select_location():
    locations = db.session.query(Theater.city).distinct().all()
    locations = [loc[0] for loc in locations]
    if request.method == 'POST':
        location = request.form.get('location')
        return render_template('events.html', events=get_events_by_location(location), location=location)
    return render_template('select_location.html', locations=locations)

@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/confirmation')
def confirmation():
    return render_template('confirmation.html')

@app.route('/event/<int:event_id>')
def event_detail(event_id):
    show = Show.query.get_or_404(event_id)
    theater = Theater.query.get(show.theater_id)
    event = {
        'id': show.id,
        'title': show.name,
        'description': f"At {theater.name}, {theater.city}",
        'image': '/static/event_default.jpg',
        'date': show.start_time.strftime('%Y-%m-%d'),
        'location': theater.address
    }
    return render_template('event_detail.html', event=event)

@app.route('/book/<int:event_id>', methods=['GET', 'POST'])
def book_page(event_id):
    show = Show.query.get_or_404(event_id)
    theater = Theater.query.get(show.theater_id)
    event = {
        'id': show.id,
        'title': show.name,
        'description': f"At {theater.name}, {theater.city}",
        'image': '/static/event_default.jpg',
        'date': show.start_time.strftime('%Y-%m-%d'),
        'location': theater.address
    }
    seats = Seat.query.filter_by(show_id=show.id).all()
    error = None
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        quantity = int(request.form.get('quantity', 1))
        seat_ids_raw = request.form.getlist('seat_id')
        if len(seat_ids_raw) != quantity:
            error = f'Please select {quantity} seat(s).'
            return render_template('book.html', event=event, seats=seats, error=error, quantity=quantity, selected_seats=seat_ids_raw)
        session['booking_details'] = {
            'name': name,
            'email': email,
            'quantity': quantity,
            'seat_ids': seat_ids_raw,
            'event_id': event_id
        }
        return redirect(url_for('payment_page'))
    return render_template('book.html', event=event, seats=seats, error=error)

@app.route('/payment', methods=['GET', 'POST'])
def payment_page():
    details = session.get('booking_details')
    if not details:
        return redirect(url_for('home'))
    if request.method == 'POST':
        user_id = session.get('user_id')
        event_id = details['event_id']
        show = Show.query.get(event_id)
        for seat_id in details['seat_ids']:
            seat = Seat.query.get(int(seat_id))
            if seat and not seat.is_booked and user_id:
                seat.is_booked = True
                db.session.commit()
                booking = Booking(
                    user_id=user_id,
                    show_id=show.id,
                    seat_id=seat.id,
                    payment_status="confirmed"
                )
                db.session.add(booking)
                db.session.commit()
        session.pop('booking_details', None)
        return render_template('confirmation.html', event={
            'title': show.name,
            'image': '/static/event_default.jpg'
        }, name=details['name'], email=details['email'], quantity=details['quantity'])
    return render_template('payment.html')

@app.route('/events-cached', methods=['GET', 'POST'])
def events_cached_page():
    if request.method == 'POST':
        location = request.form.get('location')
        key = f"events_{location}"
        events = cache.get(key)
        app.logger.info(f"[CACHE] GET {key}: {bool(events)}")
        if not events:
            events = get_events_by_location(location)
            cache.set(key, events)
            app.logger.info(f"[CACHE] SET {key}")
        return render_template('events.html', events=events, location=location, cached=True)
    location = request.args.get('location')
    if not location:
        locations = [loc[0] for loc in db.session.query(Theater.city).distinct().all()]
        return render_template('select_location.html', locations=locations)
    key = f"events_{location}"
    events = cache.get(key)
    app.logger.info(f"[CACHE] GET {key}: {bool(events)}")
    if not events:
        events = get_events_by_location(location)
        cache.set(key, events)
        app.logger.info(f"[CACHE] SET {key}")
    return render_template('events.html', events=events, location=location, cached=True)


def get_events_by_location(location):
    shows = Show.query.join(Theater, Show.theater_id == Theater.id).filter(Theater.city == location).limit(10).all()
    events = []
    for show in shows:
        theater = Theater.query.get(show.theater_id)
        events.append({
            'id': show.id,
            'title': show.name,
            'description': f"At {theater.name}, {theater.city}",
            'image': '/static/event_default.jpg',
            'date': show.start_time.strftime('%Y-%m-%d'),
            'location': theater.address
        })
    return events

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True)
    email = db.Column(db.String(120), unique=True)
    password_hash = db.Column(db.String(128))

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)


class Theater(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    city = db.Column(db.String(50))
    address = db.Column(db.String(200))


class Show(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150))
    theater_id = db.Column(db.Integer)
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    price = db.Column(db.Integer)


class Seat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    show_id = db.Column(db.Integer)
    seat_number = db.Column(db.String(10))
    is_booked = db.Column(db.Boolean, default=False)


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    show_id = db.Column(db.Integer)
    seat_id = db.Column(db.Integer)
    payment_status = db.Column(db.String(20), default="pending")
    booking_time = db.Column(db.DateTime, default=datetime.utcnow)


class Ticket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer)
    ticket_code = db.Column(db.String(20))

def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **k):
        if "user_id" not in session:
            return jsonify({"error": "login required"}), 401
        return fn(*a, **k)
    return wrapper


@app.route('/register', methods=['GET', 'POST'])
def register_page():
    error = None
    if request.method == 'POST':
        if request.is_json:
            d = request.get_json()
            username = d.get('username', d.get('email', '').split('@')[0])
            email = d.get('email')
            password = d.get('password')
        else:
            username = request.form.get('username')
            email = request.form.get('email')
            password = request.form.get('password')
        if not username or not email or not password:
            error = 'All fields required.'
            if request.is_json:
                return jsonify({'error': error}), 400
        elif User.query.filter_by(email=email).first():
            error = 'Email already registered.'
            if request.is_json:
                return jsonify({'error': error}), 400
        else:
            user = User(username=username, email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            if request.is_json:
                session['user_id'] = user.id
                return jsonify({'message': 'registered', 'user_id': user.id})
            return redirect(url_for('login'))
    return render_template('register.html', error=error)

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    error = None
    if request.method == 'POST':
        if request.is_json:
            d = request.get_json()
            email = d.get('email')
            password = d.get('password')
        else:
            email = request.form.get('email')
            password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            error = 'Invalid email or password.'
            if request.is_json:
                return jsonify({'error': error}), 400
        else:
            session['user_id'] = user.id
            session['username'] = user.username
            if request.is_json:
                return jsonify({'message': 'logged in'})
            return redirect(url_for('home'))
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/my-bookings')
def my_bookings():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    bookings = Booking.query.filter_by(user_id=user_id).all()
    results = []
    for booking in bookings:
        show = Show.query.get(booking.show_id)
        seat = Seat.query.get(booking.seat_id)
        results.append({
            'movie': show.name,
            'seat': seat.seat_number,
            'time': show.start_time.strftime('%Y-%m-%d %H:%M'),
            'status': booking.payment_status
        })
    return render_template('my_bookings.html', bookings=results)


@app.route("/api/shows/<city>")
def shows_by_city(city):
    key = f"shows_{city}"
    cached = cache.get(key)

    if cached:
        return jsonify({
            "cache": "HIT",
            "data": cached
        })

    theaters = Theater.query.filter_by(city=city).all()
    result = []

    for t in theaters:
        shows = Show.query.filter_by(theater_id=t.id).all()
        for s in shows:
            result.append({
                "show_id": s.id,
                "name": s.name,
                "theater": t.name,
                "time": s.start_time.strftime("%Y-%m-%d %H:%M"),
                "price": s.price
            })

    cache.set(key, result)

    return jsonify({
        "cache": "MISS",
        "data": result
    })



@app.route("/api/book", methods=["POST"])
@login_required
def book():
    d = request.json
    seat = Seat.query.get(d["seat_id"])
    if not seat or seat.is_booked:
        return jsonify({"error": "seat unavailable"}), 400

    booking = Booking(
        user_id=session["user_id"],
        show_id=d["show_id"],
        seat_id=d["seat_id"]
    )
    db.session.add(booking)
    db.session.commit()
    return jsonify({"booking_id": booking.id})


@app.route("/api/pay/<int:booking_id>", methods=["POST"])
@login_required
def pay(booking_id):
    b = Booking.query.get(booking_id)
    if not b or b.user_id != session["user_id"]:
        return jsonify({"error": "booking not found"}), 404

    seat = Seat.query.get(b.seat_id)
    seat.is_booked = True
    b.payment_status = "confirmed"

    ticket = Ticket(
        booking_id=b.id,
        ticket_code=str(uuid.uuid4())[:8].upper()
    )

    db.session.add(ticket)
    db.session.commit()
    cache.clear()
    return jsonify({"ticket": ticket.ticket_code})


def init_data():
    if Theater.query.first():
        return

    cities = ["Chennai", "Mumbai", "Delhi", "Bangalore", "Hyderabad"]
    movies = ["Coolie", "Vedhalam", "Idly Kadai", "JanaNayagan", "Dhurandhar"]

    theater_data = [
        ("Majestic", "Chennai", "Anna Salai"),
        ("Regal", "Mumbai", "Colaba"),
        ("PVR", "Delhi", "Connaught Place"),
        ("INOX", "Bangalore", "MG Road"),
        ("Prasads", "Hyderabad", "Necklace Road")
    ]

    for name, city, address in theater_data:
        t = Theater(name=name, city=city, address=address)
        db.session.add(t)
        db.session.flush()
        for m in movies:
            s = Show(
                name=m,
                theater_id=t.id,
                start_time=datetime.now() + timedelta(days=random.randint(1, 10)),
                end_time=datetime.now() + timedelta(days=random.randint(1, 10), hours=3),
                price=random.choice([200, 250, 300])
            )
            db.session.add(s)
            db.session.flush()
            for r in ["A", "B"]:
                for n in range(1, 11):
                    db.session.add(Seat(
                        show_id=s.id,
                        seat_number=f"{r}{n}"
                    ))
    db.session.commit()
    print("Sample movies and seats created")

with app.app_context():
    db.create_all()
    init_data()

if __name__ == "__main__":
    app.run(debug=True)
