extends RefCounted
## Approximate geometric sun direction using NOAA's general solar equations.
## https://gml.noaa.gov/grad/solcalc/solareqns.PDF
## No refraction, topocentric correction, weather, seasons or calendar evolution.
const LATITUDE: float = 37.7793
const LONGITUDE: float = -122.4193
const REPRESENTATIVE_DAY: int = 249 # September 6 in a non-leap year.
const UTC_OFFSET: float = -7.0 # PDT for this representative September day.

static func sample(clock_seconds: float, latitude: float = LATITUDE, longitude: float = LONGITUDE, day_of_year: int = REPRESENTATIVE_DAY, utc_offset: float = UTC_OFFSET, days_in_year: int = 365) -> Dictionary:
	if not is_finite(clock_seconds) or not is_finite(latitude) or not is_finite(longitude) or not is_finite(utc_offset): return {}
	if absf(latitude) > 90.0 or absf(longitude) > 180.0 or absf(utc_offset) > 14.0 or days_in_year not in [365,366] or day_of_year < 1 or day_of_year > days_in_year: return {}
	var seconds: float = fposmod(clock_seconds,86400.0)
	var hour: float = seconds / 3600.0
	var gamma: float = TAU/float(days_in_year)*(float(day_of_year)-1.0+(hour-12.0)/24.0)
	var equation_minutes: float = 229.18*(0.000075+0.001868*cos(gamma)-0.032077*sin(gamma)-0.014615*cos(2.0*gamma)-0.040849*sin(2.0*gamma))
	var declination: float = 0.006918-0.399912*cos(gamma)+0.070257*sin(gamma)-0.006758*cos(2.0*gamma)+0.000907*sin(2.0*gamma)-0.002697*cos(3.0*gamma)+0.00148*sin(3.0*gamma)
	var solar_minutes: float = fposmod(seconds/60.0+equation_minutes+4.0*longitude-60.0*utc_offset,1440.0)
	var angle: float = deg_to_rad(solar_minutes/4.0-180.0)
	var latitude_radians: float = deg_to_rad(latitude)
	# A local east/north/up unit vector avoids ambiguous azimuth quadrants.
	var east: float = -cos(declination)*sin(angle)
	var north: float = cos(latitude_radians)*sin(declination)-sin(latitude_radians)*cos(declination)*cos(angle)
	var up: float = sin(latitude_radians)*sin(declination)+cos(latitude_radians)*cos(declination)*cos(angle)
	var altitude: float = rad_to_deg(asin(clampf(up,-1.0,1.0)))
	var azimuth: float = fposmod(rad_to_deg(atan2(east,north)),360.0)
	return {"clock_seconds":seconds,"altitude_degrees":altitude,"azimuth_degrees":azimuth,"direction":Vector3(east,up,-north).normalized(),"equation_of_time_minutes":equation_minutes,"phase":"night" if altitude < -6.0 else ("twilight" if altitude < 0.0 else "daylight")}
