CREATE TABLE #TMP_LIST
	(
        -- Everything that has 'OLD' in front is what is found via a procedure regarding the last diagnostician of the SAME EXAM TYPE (EXAMNUMCODE)
		OLDEXAM		INT,            -- Last Exam Type ID
		OLDVISIT	INT,            -- Last Visit ID
		OLDORDER	DATE,           -- Last Visit Date
		OLDPERS		INT,            -- Last time's same exam type Diagnostician ID assigned
		OLDDIAGNOSTIS VARCHAR(100), -- Last time's same exam type Diagnostician Name assigned
		AA		    INT,            -- This can be omitted
        -- EXTRACODE and VISITID are unique per visit and they are different. Each visit might include multiple exams. VISITID can be omitted
		EXTRACODE	INT,
		VISITID		INT,
		DEMOGID		INT,            -- Patient's ID
		FNAME		VARCHAR(100),   -- Patient's First Name
		LNAME		VARCHAR(100),   -- Patient's Last Name
		EXAMID		INT,            -- This can be omitted
		EXAMNUMCODE	INT,            -- Exam Type
		EXAMNAME	VARCHAR(200),   -- Exam Type Name
		VISITDATE	DATE,           -- Visit Date
		LABCODEID	INT,            -- Lab ID
		LABORATORYNAME	VARCHAR(100), -- Lab Name
		WARDID		INT,            -- This can be omitted
		WCODE		VARCHAR(20),    -- Issuing doctor ID
		WNAME		VARCHAR(100),   -- Issuing doctor Name
		DIAGNOSTIS	INT,            -- Diagnostician ID (when assigned)
		PERSONELID	INT,            -- This can be omitted (same as DIAGNOSTIS)
		CODE		VARCHAR(100),   -- Diagnostician's Name
		NAME		VARCHAR(100),   -- This can be omitted (includes the name of the Diagnostician again)
		NOTES		VARCHAR(MAX),   -- Notes/Comments/Remarks (because it takes data from 3 fields, they are seperated by '*')
		EXAMMOREID	INT,            -- Unique Exam ID
		CATEGORY	VARCHAR(50)     -- Exam Category (either ΜΑΓΝΗΤΙΚΗ or ΑΞΟΝΙΚΗ)
	)



EXEC getWardDoctors
EXEC getExamsListForPeriod '2026-07-29','2026-07-31'
