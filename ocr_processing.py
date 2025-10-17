import logging
import re
import cv2
import pytesseract
from difflib import SequenceMatcher

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# OCR HELPER FUNCTIONS
# =============================================================================

def adjust_brightness_contrast(image, alpha=1.0, beta=0):
    """Adjust brightness and contrast of an image."""
    return cv2.convertScaleAbs(image, alpha=alpha, beta=beta)

def perform_ocr(segment, label):
    """Performs OCR on the given segment with several preprocessing steps."""
    try:
        # Names allow letters, digits, a few Discord-ish glyphs; stats are numeric/percent
        if label == "Name":
            custom_config = r'--oem 3 --psm 7 -c tessedit_char_whitelist=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ<>#0123456789_ '
        else:
            custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=.0123456789%'

        def preprocess_original(seg): return seg
        def preprocess_grayscale(seg): return cv2.cvtColor(seg, cv2.COLOR_BGR2GRAY)
        def preprocess_threshold(seg):
            gray = cv2.cvtColor(seg, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            return thresh
        def preprocess_blur(seg):
            gray = cv2.cvtColor(seg, cv2.COLOR_BGR2GRAY)
            return cv2.GaussianBlur(gray, (5, 5), 0)
        def preprocess_adaptive_threshold(seg):
            gray = cv2.cvtColor(seg, cv2.COLOR_BGR2GRAY)
            return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 2)
        def preprocess_brightness_contrast(seg):
            gray = cv2.cvtColor(seg, cv2.COLOR_BGR2GRAY)
            return adjust_brightness_contrast(gray, alpha=1.5, beta=30)

        preprocessing_methods = [
            preprocess_original,
            preprocess_grayscale,
            preprocess_threshold,
            preprocess_blur,
            preprocess_adaptive_threshold,
            preprocess_brightness_contrast
        ]

        for preprocess in preprocessing_methods:
            preprocessed_segment = preprocess(segment)
            text = pytesseract.image_to_string(preprocessed_segment, config=custom_config).strip()
            logger.info(f"OCR raw text for label '{label}': '{text}'")
            if text:
                # Heuristic second pass for zero-prone fields misread as '8'
                if label in {"Melee Kills", "Samples Extracted"} and text in {"8", "88"}:
                    try:
                        cfg_no8 = r'--oem 3 --psm 10 -c tessedit_char_whitelist=0123456789 -c tessedit_char_blacklist=8'
                        text2 = pytesseract.image_to_string(preprocessed_segment, config=cfg_no8).strip()
                        logger.info(f"OCR recheck (no '8') for '{label}': '{text2}'")
                        if text2 and text2 != text:
                            return text2
                    except Exception as e:
                        logger.warning(f"Secondary OCR pass failed for '{label}': {e}")
                return text
        return None
    except Exception as e:
        logger.error(f"OCR error for label '{label}': {e}")
        return None

def clean_ocr_result(text, label):
    """Cleans the OCR result based on the label."""
    if not text:
        return None

    logger.info(f"Original text for label '{label}': '{text}'")

    NUMERIC_FIELDS = {
        "Shots Fired", "Shots Hit", "Kills", "Deaths", "Melee Kills",
        # NEW:
        "Stims Used", "Samples Extracted", "Stratagems Used"
    }

    if label == "Name":
        misreads = {
            '2': 'Z', '3': 'E', '4': 'A', '5': 'S', '6': 'G', '7': 'T', '8': 'B', '9': 'G',
            '|': 'I', '@': 'A', '$': 'S', '&': 'E', '!': 'I', '£': 'E', '€': 'E',
        }
        for wrong, right in misreads.items():
            text = text.replace(wrong, right)
        text = text.replace('_', ' ')
        text = re.sub(r'([A-Za-z0-9])([A-Z])$', r'\1', text)
        text = re.sub(r'\s+', ' ', text).strip()
        text = re.sub(r'[^A-Za-z0-9\s]', ' ', text)
    elif label in NUMERIC_FIELDS:
        # Aggressive OCR correction for digits-only fields
        # Cautious mappings; avoid biasing zeros to eights
        text = (text.replace('O', '0').replace('o', '0')
                    .replace('l', '1').replace('I', '1')
                    .replace('S', '5'))
        # For fields that are frequently 0, avoid auto-mapping 'B'->'8'
        if label not in {"Melee Kills", "Samples Extracted"}:
            text = text.replace('B', '8')
        text = re.sub(r'[^\d]', '', text)
    elif label == "Accuracy":
        text = re.sub(r'[^\d\.%]', '', text)
    else:
        text = re.sub(r'[^\d]', '', text)

    logger.info(f"Cleaned text for label '{label}': '{text}'")

    if not text:
        return None

    return text

def process_for_ocr(image, regions, NUM_PLAYERS=None):
    """
    Extracts and cleans text for each player column present in the image.
    Only returns players with a valid name (not blank/junk).
    """
    # --- AUTO-DETECT NUMBER OF PLAYER COLUMNS PRESENT ---
    player_nums = []
    for key in regions.keys():
        match = re.match(r'P(\d+) Name', key)
        if match:
            player_nums.append(int(match.group(1)))

    max_player_index = max(player_nums) if player_nums else 0

    # Always process 2-4 columns if present, but skip if there are no columns at all.
    if max_player_index == 0:
        return []

    # Determine how many player columns to process (2, 3, or 4)
    if NUM_PLAYERS is None or not isinstance(NUM_PLAYERS, int):
        NUM_PLAYERS = max(max_player_index, 2)
    NUM_PLAYERS = min(max(NUM_PLAYERS, 2), 4)  # always at least 2, at most 4

    # Fields we will attempt to read for each player column (must match your region keys)
    # Removed 'Accuracy' from scanning; it will be calculated from Shots Fired/Hit.
    BASE_FIELDS = ['Name', 'Kills', 'Shots Fired', 'Shots Hit', 'Deaths', 'Melee Kills']
    EXTRA_FIELDS = ['Stims Used', 'Samples Extracted', 'Stratagems Used']  # NEW
    ALL_FIELDS = BASE_FIELDS + EXTRA_FIELDS

    player_data = []
    for player_index in range(NUM_PLAYERS):
        player_stats = {}
        shots_fired = 0
        shots_hit = 0

        for key in ALL_FIELDS:
            label = f"P{player_index + 1} {key}"
            segment = regions.get(label)
            if segment is None:
                logger.debug(f"Label {label} not found in regions.")
                player_stats[label] = "0"
                continue

            x1, y1, x2, y2 = segment
            image_segment = image[y1:y2, x1:x2]
            ocr_result = perform_ocr(image_segment, key)
            if not ocr_result:
                logger.debug(f"OCR failed for {label}. No text extracted.")
                player_stats[label] = "0"
                continue

            cleaned_result = clean_ocr_result(ocr_result, key)
            if not cleaned_result:
                logger.debug(f"Failed to clean OCR result for {label}. Raw: '{ocr_result}'")
                player_stats[label] = "0"
                continue

            # Store or parse data
            if key == "Name":
                player_stats[label] = cleaned_result
            elif key == "Shots Fired":
                try:
                    shots_fired = int(cleaned_result)
                except ValueError:
                    shots_fired = 0
            elif key == "Shots Hit":
                try:
                    shots_hit = int(cleaned_result)
                except ValueError:
                    shots_hit = 0
            # 'Accuracy' is no longer OCR-scanned; it will be computed below
            elif key in {"Melee Kills", "Stims Used", "Samples Extracted", "Stratagems Used"}:
                try:
                    player_stats[label] = int(cleaned_result)
                except ValueError:
                    player_stats[label] = 0
            else:
                # Fallback numeric
                player_stats[label] = cleaned_result

        # Correct Shots Hit if bigger than Shots Fired
        if shots_hit > shots_fired:
            logger.warning(
                f"Shots Hit exceeds Shots Fired for Player {player_index + 1}. "
                f"Recalculating Shots Hit to {shots_fired}."
            )
            shots_hit = shots_fired

        # Calculate accuracy from shots; allow zeros
        accuracy = (shots_hit / shots_fired) * 100 if shots_fired > 0 else 0
        accuracy = min(accuracy, 100.0)

        # Build final dict with standardized keys
        formatted_player = {}
        for k, v in player_stats.items():
            splitted = k.split(" ", 1)
            if len(splitted) == 2:
                field_key = splitted[1]
                if field_key == "Name":
                    field_key = "player_name"
            else:
                field_key = k
            formatted_player[field_key] = v

        # Ensure numeric casts
        try:
            formatted_player["Shots Fired"] = shots_fired
        except Exception:
            formatted_player["Shots Fired"] = 0
        try:
            formatted_player["Shots Hit"] = shots_hit
        except Exception:
            formatted_player["Shots Hit"] = 0
        try:
            formatted_player["Melee Kills"] = int(formatted_player.get("Melee Kills", 0))
        except Exception:
            formatted_player["Melee Kills"] = 0
        # NEW numeric fields
        for nf in ("Stims Used", "Samples Extracted", "Stratagems Used"):
            try:
                formatted_player[nf] = int(formatted_player.get(nf, 0))
            except Exception:
                formatted_player[nf] = 0

        formatted_player["Accuracy"] = f"{accuracy:.1f}%"

        # Append even if name is blank so the user can manually register later
        name_check = (formatted_player.get("player_name") or "").strip().lower()
        if name_check in ["0", ".", "a"]:
            formatted_player["player_name"] = None
        player_data.append(formatted_player)
        logger.debug(f"OCR extracted (including blanks) for player {player_index + 1}: {formatted_player}")

    return player_data

# =============================================================================
# PARTIAL MATCHING LOGIC (IMPROVED)
# =============================================================================

def find_best_partial_match(ocr_name: str, registered_names: list[str], threshold: float = 70.0, min_len: int = 4):
    """
    Attempts to find the best partial match for 'ocr_name' within 'registered_names'.
    Does NOT allow substring matches for names < min_len.
    """
    ocr_name = ocr_name.strip()
    if len(ocr_name) < min_len:
        # Only allow exact (case-insensitive) match if the name is very short
        for db_name in registered_names:
            if ocr_name.lower() == db_name.lower():
                logger.info(f"Exact match for short name '{ocr_name}'.")
                return db_name, 100.0
        logger.info(f"No exact match for short name '{ocr_name}'.")
        return None, 0.0

    best_match = None
    best_score = 0.0
    ocr_name_lower = ocr_name.lower()

    for db_name in registered_names:
        db_name_lower = db_name.lower()
        ratio_full = SequenceMatcher(None, ocr_name_lower, db_name_lower).ratio() * 100
        substring_bonus = 20 if (len(ocr_name_lower) >= min_len and len(db_name_lower) >= min_len and
                                 (ocr_name_lower in db_name_lower or db_name_lower in ocr_name_lower)) else 0
        if abs(len(ocr_name_lower) - len(db_name_lower)) > 3:
            continue
        score = ratio_full + substring_bonus
        if score > best_score:
            best_score = score
            best_match = db_name
    if best_score >= threshold:
        return best_match, best_score
    else:
        return None, 0.0

def match_player_names(ocr_players, registered_users, threshold=70.0):
    """
    Partial match each OCR'd player_name against registered users list.
    :param ocr_players: list of dicts from process_for_ocr() with 'player_name'
    :param registered_users: list of known player names (e.g., from your DB)
    :param threshold: match score threshold
    :return: same list, but with a 'matched_user' key if found
    """
    for p in ocr_players:
        ocr_name = p.get('player_name')
        if not ocr_name:
            logger.info(f"No OCR name found for {p}. Skipping.")
            continue

        best_match, best_score = find_best_partial_match(ocr_name, registered_users, threshold=threshold)
        if best_match:
            logger.info(f"Best match for '{ocr_name}' is '{best_match}' with a score of {best_score:.1f}.")
            p['matched_user'] = best_match
        else:
            logger.info(f"No good match found for '{ocr_name}'.")
            p['matched_user'] = None

    return ocr_players
