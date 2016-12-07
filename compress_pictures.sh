
#list all files in the current directory without recursing and put the compressed image on the ''comp'' subdirectory

find -maxdepth 1 -type f -print0 | xargs -r -0 -ixxx  xxx ./comp/xxx.jpg

#for all the files with weird extension, e.g. JPG, this leads to an additional extension, fix this:
(cd comp/
for i in *.JPG.jpg; do mv $i ${i%.JPG.jpg}.jpg; done
)

#recreate the modified date from EXIF information
(cd comp/
for i in *.jpg; do
    touch -t $(exiftool -p '$DateTimeOriginal' $i  | sed 's/[: ]//g' | sed 's/\(..$\)/\.\1/') $i
done
)

#Or just use jhead and do this in the directory.
#Code:
# jhead -ft *.jpg

#DATE / TIME MANIPULATION:
#  -ft        Set file modification time to Exif time
