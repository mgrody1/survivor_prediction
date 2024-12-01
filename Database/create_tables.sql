CREATE TABLE Season_Summary (
   version TEXT,
   version_season VARCHAR(255) PRIMARY KEY,
   season_name TEXT,
   season INT,
   location TEXT,
   country TEXT,
   tribe_setup TEXT,
   n_cast INT,
   n_tribes INT,
   n_finalists INT,
   n_jury INT,
   full_name TEXT,
   winner_id VARCHAR(255),
   winner TEXT,
   runner_ups TEXT,
   final_vote TEXT,
   timeslot TEXT,
   premiered DATE,
   ended DATE,
   filming_started DATE,
   filming_ended DATE,
   viewers_reunion FLOAT,
   viewers_premiere INT,
   viewers_finale INT,
   viewers_mean FLOAT,
   rank INT
);
-- Advantage Details Table
CREATE TABLE Advantage_Details (
   version TEXT,
   version_season VARCHAR(255),
   season_name TEXT,
   season INT,
   advantage_id INT,
   advantage_type TEXT,
   clue_details TEXT,
   location_found TEXT,
   conditions TEXT,
   PRIMARY KEY (version_season, advantage_id),
   FOREIGN KEY (version_season) REFERENCES Season_Summary(version_season) ON DELETE CASCADE
);
-- Advantage Movement Table
CREATE TABLE Advantage_Movement (
   version TEXT,
   version_season VARCHAR(255),
   season_name TEXT,
   season INT,
   castaway TEXT,
   castaway_id VARCHAR(255),
   advantage_id INT,
   sequence_id INT,
   day INT,
   episode INT,
   event TEXT,
   played_for TEXT,
   played_for_id VARCHAR(255),
   success BOOLEAN,
   votes_nullified FLOAT,
   PRIMARY KEY (version_season, advantage_id, sequence_id),
   FOREIGN KEY (version_season) REFERENCES Season_Summary(version_season) ON DELETE CASCADE
);
-- Boot Mapping Table
CREATE TABLE Boot_Mapping (
	boot_mapping_id SERIAL PRIMARY KEY,
   version TEXT,
   version_season VARCHAR(255),
   season_name TEXT,
   season INT,
   episode INT,
   boot_mapping_order INT, -- Renamed field
   n_boots INT,
   final_n INT,
   sog_id INT,
   castaway_id VARCHAR(255),
   castaway TEXT,
   tribe TEXT,
   tribe_status TEXT,
   game_status TEXT,
   FOREIGN KEY (version_season) REFERENCES Season_Summary(version_season) ON DELETE CASCADE
);

-- Castaways Table
CREATE TABLE Castaways (
   version TEXT,
   version_season VARCHAR(255),
   season_name TEXT,
   season INT,
   full_name TEXT,
   castaway_id VARCHAR(255),
   castaway TEXT,
   age INT,
   city TEXT,
   state TEXT,
   episode INT,
   day INT,
   castaways_order INT, -- Renamed field
   castaways_result TEXT, -- Renamed field
   jury_status TEXT,
   original_tribe TEXT,
   jury BOOLEAN,
   finalist BOOLEAN,
   winner BOOLEAN,
   result_number INT,
   acknowledge BOOLEAN,
   ack_look BOOLEAN,
   ack_speak BOOLEAN,
   ack_gesture BOOLEAN,
   ack_smile BOOLEAN,
   ack_quote TEXT,
   ack_score INT,
   PRIMARY KEY (version_season, castaway_id),
   FOREIGN KEY (version_season) REFERENCES Season_Summary(version_season) ON DELETE cascade
);

-- Castaway Details Table
CREATE TABLE Castaway_Details (
   castaway_id VARCHAR(255) PRIMARY KEY,
   full_name TEXT,
   full_name_detailed TEXT,
   castaway TEXT,
   date_of_birth DATE,
   date_of_death DATE,
   gender TEXT,
   african BOOLEAN,
   asian BOOLEAN,
   latin_american BOOLEAN,
   native_american BOOLEAN,
   bipoc BOOLEAN,
   lgbt BOOLEAN,
   personality_type TEXT,
   occupation TEXT,
   three_words TEXT,
   hobbies TEXT,
   pet_peeves TEXT,
   race TEXT,
   ethnicity text
);

-- Tribe Mapping Table
CREATE TABLE Tribe_Mapping (
	tribe_map_id SERIAL PRIMARY KEY,
   version TEXT,
   version_season VARCHAR(255),
   season_name TEXT,
   season INT,
   episode INT,
   day INT,
   castaway_id VARCHAR(255),
   castaway TEXT,
   tribe TEXT,
   tribe_status TEXT,
   FOREIGN KEY (version_season) REFERENCES Season_Summary(version_season) ON DELETE CASCADE
);
-- Episode Summary Table
CREATE TABLE Episode_Summary (
	episode_summary_id SERIAL PRIMARY KEY,
   version TEXT,
   version_season VARCHAR(255),
   episode INT,
   episode_summary TEXT,
   FOREIGN KEY (version_season) REFERENCES Season_Summary(version_season) ON DELETE CASCADE
);
-- Confessionals Table
CREATE TABLE Confessionals (
	confessional_id SERIAL PRIMARY KEY,
   version TEXT,
   version_season VARCHAR(255),
   season_name TEXT,
   season INT,
   episode INT,
   castaway TEXT,
   castaway_id VARCHAR(255),
   confessional_count INT,
   confessional_time FLOAT,
   index_count INT,
   index_time FLOAT,
   FOREIGN KEY (version_season) REFERENCES Season_Summary(version_season) ON DELETE CASCADE
);
-- Challenge Description Table
CREATE TABLE Challenge_Description (
   version TEXT,
   version_season VARCHAR(255),
   season_name TEXT,
   season INT,
   episode INT,
   challenge_id INT,
   challenge_number INT,
   challenge_type TEXT,
   name TEXT,
   recurring_name TEXT,
   description TEXT,
   reward TEXT,
   additional_stipulation TEXT,
   balance BOOLEAN,
   balance_ball BOOLEAN,
   balance_beam BOOLEAN,
   endurance BOOLEAN,
   fire BOOLEAN,
   food BOOLEAN,
   knowledge BOOLEAN,
   memory BOOLEAN,
   mud BOOLEAN,
   obstacle_blindfolded BOOLEAN,
   obstacle_cargo_net BOOLEAN,
   obstacle_chopping BOOLEAN,
   obstacle_combination_lock BOOLEAN,
   obstacle_digging BOOLEAN,
   obstacle_knots BOOLEAN,
   obstacle_padlocks BOOLEAN,
   precision BOOLEAN,
   precision_catch BOOLEAN,
   precision_roll_ball BOOLEAN,
   precision_slingshot BOOLEAN,
   precision_throw_balls BOOLEAN,
   precision_throw_coconuts BOOLEAN,
   precision_throw_rings BOOLEAN,
   precision_throw_sandbags BOOLEAN,
   puzzle BOOLEAN,
   puzzle_slide BOOLEAN,
   puzzle_word BOOLEAN,
   race BOOLEAN,
   strength BOOLEAN,
   turn_based BOOLEAN,
   water BOOLEAN,
   water_paddling BOOLEAN,
   water_swim BOOLEAN,
   PRIMARY KEY (version_season, challenge_id),
   FOREIGN KEY (version_season) REFERENCES Season_Summary(version_season) ON DELETE CASCADE
);
-- Challenge Results Table
CREATE TABLE Challenge_Results (
   version TEXT,
   version_season VARCHAR(255),
   season_name TEXT,
   season INT,
   episode INT,
   n_boots INT,
   castaway_id VARCHAR(255),
   castaway TEXT,
   tribe TEXT,
   tribe_status TEXT,
   challenge_type TEXT,
   outcome_type TEXT,
   team TEXT,
   challenge_results_result TEXT, -- Renamed field
   result_notes TEXT,
   chosen_for_reward BOOLEAN,
   challenge_id INT,
   sit_out BOOLEAN,
   order_of_finish INT,
   sog_id INT,
   PRIMARY KEY (version_season, challenge_id, sog_id, castaway_id),
   FOREIGN KEY (version_season) REFERENCES Season_Summary(version_season) ON DELETE CASCADE
);
-- Vote History Table
CREATE TABLE Vote_History (
	vote_history_id SERIAL PRIMARY KEY,
   version TEXT,
   version_season VARCHAR(255),
   season_name TEXT,
   season INT,
   episode INT,
   day INT,
   tribe_status TEXT,
   tribe TEXT,
   castaway TEXT,
   immunity BOOLEAN,
   vote TEXT,
   vote_event TEXT,
   vote_event_outcome TEXT,
   split_vote BOOLEAN,
   nullified BOOLEAN,
   tie BOOLEAN,
   voted_out TEXT,
   vote_history_order INT, -- Renamed field
   vote_order INT,
   castaway_id VARCHAR(255),
   vote_id VARCHAR(255),
   voted_out_id VARCHAR(255),
   sog_id INT,
   challenge_id INT,
   FOREIGN KEY (version_season) REFERENCES Season_Summary(version_season) ON DELETE cascade
);
-- Episodes Table
CREATE TABLE Episodes (
   version TEXT,
   version_season VARCHAR(255),
   season_name TEXT,
   season INT,
   episode_number_overall INT,
   episode INT,
   episode_title TEXT,
   episode_label TEXT,
   episode_date DATE,
   episode_length FLOAT,
   viewers FLOAT,
   imdb_rating FLOAT,
   n_ratings INT,
   episode_summary_wiki TEXT,
   episode_summary TEXT,
   PRIMARY KEY (version_season, episode),
   FOREIGN KEY (version_season) REFERENCES Season_Summary(version_season) ON DELETE CASCADE
);
-- Jury Votes Table
CREATE TABLE Jury_Votes (
	jury_vote_id SERIAL PRIMARY KEY,
   version TEXT,
   version_season VARCHAR(255),
   season_name TEXT,
   season INT,
   castaway TEXT,
   finalist TEXT,
   vote TEXT,
   castaway_id VARCHAR(255),
   finalist_id VARCHAR(255),
   FOREIGN KEY (version_season) REFERENCES Season_Summary(version_season) ON DELETE CASCADE
);